from typing import Dict, Any, List, Optional
from src.agents.tool_agents.base_tool_agent import BaseToolAgent
#from TransLatex.src.formats.latex.prompts import *
import src.formats.latex.prompts as pm
from src.formats.latex.utils import *
from pathlib import Path
import sys
import os
import re
import regex
import asyncio
import aiohttp
import requests
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.terminology import load_term_csv, project_terms_path, merge_term_pairs
from src.utils.progress import st

base_dir = os.getcwd()
sys.path.append(base_dir)


TRANSLATION_MODE_ALIASES = {
    "plain": "plain",
    "terms": "terms",
}


def normalize_translation_mode(mode: Any) -> str:
    if mode is None:
        return "plain"
    normalized = mode.strip().lower() if isinstance(mode, str) else mode
    if normalized in TRANSLATION_MODE_ALIASES:
        return TRANSLATION_MODE_ALIASES[normalized]
    valid_modes = ", ".join(sorted(TRANSLATION_MODE_ALIASES))
    raise ValueError(f"Invalid translation mode: {mode!r}. Expected one of: {valid_modes}.")


class TranslatorAgent(BaseToolAgent):
    def __init__(self, 
                 config: Dict[str, Any], 
                 trans_mode: Any = "plain",
                 project_dir: Optional[str] = None,
                 output_dir: Optional[str] = None,
                 errors_report: Optional[List[Dict]] = None,
        ):
        super().__init__(agent_name="TranslatorAgent", config=config)
        self.config = config
        update_term = config.get("update_term", False)
        if isinstance(update_term, str):
            self.update_term = update_term.strip().lower() == "true"
        else:
            self.update_term = bool(update_term)
        self.model = config["llm_config"].get("model", "gpt-4o")
        self.base_url = config["llm_config"].get("base_url", None)
        self.API_KEY = config["llm_config"].get("api_key", None)
        self.user_term = config.get("user_term", None)
        self.target_language = config.get("target_language", "ch")
        self.category = config.get("category", None)
        self.project_dir = project_dir  # Project path for parsing
        self.output_dir = output_dir  # Output directory for parsed files
        self.fail_section_nums = []
        self.fail_caption_phs = []
        self.fail_env_phs = []
        self.have_fail_parts = False
        self.errors_report = errors_report if errors_report is not None else []
        self.trans_mode = normalize_translation_mode(trans_mode)
        self.retrying = False
        # self.term_dict = config.get("term_dict", {})  # Dictionary for terminology translation
        self.term_dict = {}
        self._project_terms_loaded = False
        self.summary = ''
        self.prev_text = ''
        self.prev_transed_text = ''
        self.currant_content = ''

    async def execute(self, error_retry_count=0, Maxtry=3):

        pm.init_prompts(self.config["source_language"], self.config["target_language"])
        self.add_placeholder()
        self.build_term_dict()

        sys.stderr = open(os.devnull, 'w')
        process_b = st.empty()
        with process_b:
            process_bar = st.progress(0)
        status_text = st.empty()
        sys.stderr = sys.__stderr__

        sections = self.read_file(Path(self.output_dir, "sections_map.json"), "json")
        captions = self.read_file(Path(self.output_dir, "captions_map.json"), "json")
        envs = self.read_file(Path(self.output_dir, "envs_map.json"), "json")

        if not self.retrying:
            self.log(f"Starting translation for project: {os.path.basename(self.project_dir)}.")

            sys.stderr = open(os.devnull, 'w')
            status_text.text(f"Starting translation for project: {os.path.basename(self.project_dir)}.")
            process_bar.progress(5)
            sys.stderr = sys.__stderr__

            async with aiohttp.ClientSession() as session:
                sem = asyncio.Semaphore(10)  # Considering the api response speed, processing one section approximately takes about 10 seconds, and initiating a call every half second, 
                                             # around 10 should not waste api tokens

                async def process_section(i, sec):
                    async with sem:
                        translated = await self.translate(sec, envs, captions, session)
                        return i, translated

                tasks = [process_section(i, sec) for i, sec in enumerate(sections)]

                completed = 0

                total_tasks = len(tasks)
                for future in asyncio.as_completed(tasks):
                    i, translated_section = await future
                    sections[i] = translated_section
                    
                    completed += 1

                    sys.stderr = open(os.devnull, 'w')
                    process = int(5 + 90 * completed / total_tasks)
                    process_bar.progress(process, text=f"Translating sections: {completed}/{total_tasks}")
                    sys.stderr = sys.__stderr__

                    # It can be considered to save and modify to integrate memory once for hard memory read and write, 
                    # and save each section once for the convenience of observing the translation situation.
                    self.save_file(Path(self.output_dir, "sections_map.json"), "json", sections)
                    self.save_file(Path(self.output_dir, "captions_map.json"), "json", captions)
                    self.save_file(Path(self.output_dir, "envs_map.json"), "json", envs)

                sys.stderr = open(os.devnull, 'w')
                status_text.text("Validating translation results...")
                process_bar.progress(95)
                sys.stderr = sys.__stderr__

                await self._val_fail_parts(Maxtry=Maxtry,
                                     sections=sections,
                                     captions=captions,
                                     envs=envs,
                                     session=session)

                sys.stderr = open(os.devnull, 'w')
                process_bar.progress(100)
                status_text.empty()
                process_b.empty()
                sys.stderr = sys.__stderr__
                self.log("Successfully translated sections.")

        else:

            sys.stderr = open(os.devnull, "w")
            status_text = st.empty()
            sys.stderr = sys.__stderr__
            async with aiohttp.ClientSession() as session:
                error_parts = [error_part["num_or_ph"] for error_part in self.errors_report]
                self.log(
                    f"Starting retranslation for error parts: {error_parts}, attempt {error_retry_count + 1}/{Maxtry}.")
                sys.stderr = open(os.devnull, "w")
                status_text.text(f"Starting retranslation for error parts: {error_parts}, attempt {error_retry_count + 1}/{Maxtry}.")
                sys.stderr = sys.__stderr__
                await self._retranslate_error_parts(secs=sections,
                                                    caps=captions,
                                                    envs=envs,
                                                    session=session)

                self.save_file(Path(self.output_dir, "sections_map.json"), "json", sections)
                self.save_file(Path(self.output_dir, "captions_map.json"), "json", captions)
                self.save_file(Path(self.output_dir, "envs_map.json"), "json", envs)

                self.fail_section_nums.clear()
                self.fail_caption_phs.clear()
                self.fail_env_phs.clear()
                self.have_fail_parts = False

                await self._val_fail_parts(Maxtry=Maxtry,
                                           sections=sections,
                                           captions=captions,
                                           envs=envs,
                                           session=session)

            sys.stderr = open(os.devnull, "w")
            status_text.empty()
            time.sleep(3)
            sys.stderr = sys.__stderr__
            self.log("Successfully retranslated error parts.")

    def enable_retranslation(self) -> None:
        self.retrying = True

    async def translate(self,
                        section: Dict[str, Any],
                        envs: List[Dict[str, Any]],
                        captions: List[Dict[str, Any]],
                        session: aiohttp.ClientSession) -> Dict[str, Any]:
        """
        Translates the input data
        """
        placeholder_pattern_cap = r"<PLACEHOLDER_CAP_\d+>"
        placeholder_pattern_env = r"<PLACEHOLDER_ENV_\d+>"
        placeholders_cap = re.findall(placeholder_pattern_cap, section["content"])
        placeholders_env = re.findall(placeholder_pattern_env, section["content"])


        if(section["section"] == "-1" or section["section"] == "0"):
            section = section
        else:
            section = await self._translate_section(section, session)  

        for placeholder in placeholders_env:
            for i, env in enumerate(envs):
                if placeholder == env["placeholder"]:
                    placeholders_cap_in_env = re.findall(placeholder_pattern_cap, env["content"])
                    placeholders_cap.extend(placeholders_cap_in_env)
                    envs[i] = await self._translate_env(env, session)  
                    break

        # remove duplicates
        placeholders_cap = list(dict.fromkeys(placeholders_cap))

        for placeholder in placeholders_cap:
            for i, caption in enumerate(captions):
                if placeholder == caption["placeholder"]:
                    captions[i] = await self._translate_caption(caption, session)  
                    break

        return section
    
    async def _val_fail_parts(self, sections, captions, envs, Maxtry, session: aiohttp.ClientSession, fail_retry_count=0) -> str:
            sys.stderr = open(os.devnull, 'w')
            status_text = st.empty()
            sys.stderr = sys.__stderr__
            while fail_retry_count < Maxtry and self.have_fail_parts:
                fail_parts = self.fail_section_nums + self.fail_caption_phs + self.fail_env_phs
                if fail_retry_count == Maxtry:  #  retry 3 times
                    print(f"Failed to translate: {fail_parts}")
                    sys.stderr = open(os.devnull, "w")
                    status_text.error(f"Failed to translate: {fail_parts}")
                    st.error(f"Failed to translate: {fail_parts}")
                    time.sleep(3)
                    sys.stderr = sys.__stderr__
                    break
                self.log(f"Starting retranslation for failed parts: {fail_parts}, attempt {fail_retry_count+1}/{Maxtry}.")
                sys.stderr = open(os.devnull, "w")
                status_text.text(f"Starting retranslation for failed parts: {fail_parts}, attempt {fail_retry_count+1}/{Maxtry}.")
                sys.stderr = sys.__stderr__
                await self._retranslate_fail_parts(secs=sections,
                                            caps=captions,
                                            envs=envs,
                                            session=session)
                self.save_file(Path(self.output_dir, "sections_map.json"), "json", sections)
                self.save_file(Path(self.output_dir, "captions_map.json"), "json", captions)
                self.save_file(Path(self.output_dir, "envs_map.json"), "json", envs)
                
                fail_retry_count += 1
                sys.stderr = open(os.devnull, 'w')
                time.sleep(3)
                status_text = st.empty()
                sys.stderr = sys.__stderr__

    async def _retranslate_fail_parts(self,
                                secs: List[Dict[str, Any]], 
                                caps: List[Dict[str, Any]], 
                                envs: List[Dict[str, Any]],
                                session: aiohttp.ClientSession) -> Any:
        sec_nums = self.fail_section_nums[:]
        cap_phs = self.fail_caption_phs[:]
        env_phs = self.fail_env_phs[:]
        self.fail_section_nums.clear()
        self.fail_caption_phs.clear()
        self.fail_env_phs.clear()
        self.have_fail_parts = False

        sec_dict = {s["section"]: i for i, s in enumerate(secs)}
        cap_dict = {c["placeholder"]: i for i, c in enumerate(caps)}
        env_dict = {e["placeholder"]: i for i, e in enumerate(envs)}

        if sec_nums:
            self.log(f"Retranslating for {sec_nums}")
            for sec_num in sec_nums:
                if sec_num == "-1" or sec_num == "0":
                    continue
                if sec_num in sec_dict:
                    i = sec_dict[sec_num]
                    secs[i] = await self._translate_section(secs[i], session)
            # else:
            #     print(f"[Warning] Section {sec_num} not found.")
        if cap_phs:
            self.log(f"Retranslating for {cap_phs}")
            for cap_ph in cap_phs:
                if cap_ph in cap_dict:
                    i = cap_dict[cap_ph]
                    caps[i] = await self._translate_caption(caps[i], session) 
            # else:
            #     print(f"[Warning] Caption placeholder {cap_ph} not found.")
        if env_phs:
            self.log(f"Retranslating for {env_phs}")
            for env_ph in env_phs:
                if env_ph in env_dict:
                    i = env_dict[env_ph]
                    envs[i] = await self._translate_env(envs[i], session) 
            # else:
            #     print(f"[Warning] Environment placeholder {env_ph} not found.")

    async def _retranslate_error_parts(self, secs, caps, envs, session) -> Any:

        async with aiohttp.ClientSession() as session:
            sem = asyncio.Semaphore(20)  

            sys.stderr = open(os.devnull, 'w')
            process_b = st.empty()
            with process_b:
                process_bar = process_b.progress(0)
            status_text = st.empty()
            sys.stderr = sys.__stderr__
            completed = 0
            async def process_ErrorPart(i, error_report):
                async with sem:
                    error_message = []
                    if "command_error" in error_report:
                        error_message.append(error_report["command_error"])
                    if "ph_error" in error_report:
                        error_message.append(error_report["ph_error"])
                    if "bracket_error" in error_report:
                        error_message.append(error_report["bracket_error"])
                    error_message = "\n".join(error_message)

                    if error_report["part"] == "sec":
                        async def process_section(i, sec):
                            async with sem:
                                if error_report["num_or_ph"] == sec["section"]:
                                    sec_async = await self._translate_section(section=sec, error_message=error_message,
                                                                              session=session)
                                    return {"index": i, "result": sec_async, "is_valid": True}
                                else:
                                    return {"index": None, "result": None, "is_valid": False}

                        tasks_sec = [process_section(i, sec) for i, sec in enumerate(secs)]
                        for future in asyncio.as_completed(tasks_sec):
                            result = await future
                            
                            if result["is_valid"]:  
                                i = result["index"]
                                _sec = result["result"]
                                secs[i] = _sec
                    elif error_report["part"] == "env":
                        async def process_env(i, env):
                            async with sem:
                                if error_report["num_or_ph"] == env["placeholder"]:
                                    env_async = await self._translate_env(env=env, error_message=error_message,
                                                                          session=session)
                                    return {"index": i, "result": env_async, "is_valid": True}
                                else:
                                    return {"index": None, "result": None, "is_valid": False}

                        tasks_env = [process_env(i, env) for i, env in enumerate(envs)]
                        for future in asyncio.as_completed(tasks_env):
                            result = await future
                            
                            if result["is_valid"]:  
                                i = result["index"]
                                _env = result["result"]
                                envs[i] = _env
                    elif error_report["part"] == "cap":
                        async def process_cap(i, cap):
                            async with sem:
                                if error_report["num_or_ph"] == cap["placeholder"]:
                                    cap_async = await self._translate_caption(caption=cap, error_message=error_message,
                                                                              session=session)
                                    return {"index": i, "result": cap_async, "is_valid": True}
                                else:
                                    return {"index": None, "result": None, "is_valid": False}

                        tasks_cap = [process_cap(i, cap) for i, cap in enumerate(caps)]
                        for future in asyncio.as_completed(tasks_cap):
                            result = await future
                            
                            if result["is_valid"]:  
                                i = result["index"]
                                _cap = result["result"]
                                caps[i] = _cap
                    return i

            tasks_ErrorPart = [process_ErrorPart(i, error_report) for i, error_report in enumerate(self.errors_report)]
            total_error_tasks = len(tasks_ErrorPart)
            for future in asyncio.as_completed(tasks_ErrorPart):
                result = await future
                completed += 1
                sys.stderr = open(os.devnull, 'w')
                process_bar.progress(completed / total_error_tasks)
                status_text.text(f"Retranslating error parts: {completed}/{total_error_tasks}")
                sys.stderr = sys.__stderr__
                
                if result is not None:  
                    i = result
            sys.stderr = open(os.devnull, 'w')
            process_bar.progress(100)
            status_text.text("Complete a retranslation once")
            time.sleep(3)
            process_b.empty()
            status_text.empty()
            sys.stderr = sys.__stderr__

    async def _translate_section(self, section: Dict[str, Any], session: aiohttp.ClientSession, error_message=None) -> Dict[str, Any]:
        
        transed_section = section.copy()
        section_num = section["section"]
        if self.retrying:
            transed_section["trans_content"] = await self._request_llm_for_retrans_error_parts(
                pm.retrans_error_parts_system_prompt,
                part=transed_section,
                error_message=error_message,
                fail_part=section_num,
                type="sec",
                session=session,
            )
        elif self._should_use_terms_prompt():
            """
            Combined with terminology translation
            """
            if not self.term_dict:
                transed_section["trans_content"] = await self._request_llm_for_trans(
                    pm.section_system_prompt,
                    section["content"],
                    fail_part=section_num,
                    type="sec",
                    session=session
                )
            else:
                transed_section["trans_content"] = await self._request_llm_for_trans_with_terms(
                                                            pm.section_system_prompt_with_dict,
                                                            section["content"], 
                                                            fail_part=section_num,
                                                            type="sec",
                                                            session=session
                                                            )

            try:
                if self.update_term == True:
                    src_text = self._extract_text_from_tex(transed_section["content"])
                    tgt_text = self._extract_text_from_tex(transed_section["trans_content"])
                    term_text = await self._request_llm_for_extract_terms(pm.extract_terminology_system_prompt,
                                                            src_text,
                                                            tgt_text,
                                                            session=session
                                                            )

                    # self._updated_term_dict(term_text)
                    self._updated_term_dict_v2(term_text)
            except Exception as e:
                return transed_section

        elif self.trans_mode == "plain":
            transed_section["trans_content"] = await self._request_llm_for_trans(
                pm.section_system_prompt,
                section["content"],
                fail_part=section_num,
                type="sec",
                session=session
            )

        return transed_section

    async def _translate_caption(self, caption: Dict[str, Any], session: aiohttp.ClientSession, error_message=None) -> Dict[str, Any]:
        """
        Translates the captions of the input data.
        """
        transed_caption = caption.copy()
        placeholder = caption["placeholder"]
        if self.retrying:
            transed_caption["trans_content"] = await self._request_llm_for_retrans_error_parts(
                pm.retrans_error_parts_system_prompt,
                part=transed_caption,
                error_message=error_message,
                fail_part=placeholder,
                type="cap",
                session=session,
            )
        elif self._should_use_terms_prompt():
            if not self.term_dict:
                transed_caption["trans_content"] = await self._request_llm_for_trans(pm.caption_system_prompt,
                                                        caption["content"], 
                                                        fail_part=placeholder,
                                                        type="cap",
                                                        session=session
                                                        )
            else:
                transed_caption["trans_content"] = await self._request_llm_for_trans_with_terms(pm.caption_system_prompt_with_dict,
                                                                                          caption["content"],
                                                                                          fail_part=placeholder,
                                                                                          type="cap",
                                                                                          session=session)
            try:
                if self.update_term == True:
                    src_text = self._extract_text_from_tex(transed_caption["content"])
                    tgt_text = self._extract_text_from_tex(transed_caption["trans_content"])
                    term_text = await self._request_llm_for_extract_terms(pm.extract_terminology_system_prompt,
                                                            src_text,
                                                            tgt_text,
                                                            session=session
                                                            )

                    # self._updated_term_dict(term_text)
                    self._updated_term_dict_v2(term_text)
            except Exception as e:
                return transed_caption

        elif self.trans_mode == "plain":
            transed_caption["trans_content"] = await self._request_llm_for_trans(pm.caption_system_prompt,
                                                        caption["content"],
                                                        fail_part=placeholder,
                                                        type="cap",
                                                        session=session
                                                        )

        return transed_caption

    async def _translate_env(self, env: Dict[str, Any], session: aiohttp.ClientSession, error_message=None) -> Dict[str, Any]:
        """
        Translates an environment block (env) based on whether translation is needed.
        """
        transed_env = env.copy()
        placeholder = env["placeholder"]
        if self.retrying:
            transed_env["trans_content"] = await self._request_llm_for_retrans_error_parts(
                pm.retrans_error_parts_system_prompt,
                part=transed_env,
                error_message=error_message,
                fail_part=placeholder,
                type="env",
                session=session,
            )
        elif self._should_use_terms_prompt():
            if not self.term_dict:
                if env["need_trans"]:
                    transed_env["trans_content"] = await self._request_llm_for_trans(pm.env_system_prompt,
                                                            env["content"], 
                                                            fail_part=placeholder,
                                                            type="env",
                                                            session=session
                                                            )
                else:
                    transed_env["trans_content"] = env["content"]
            else:
                if env["need_trans"]:
                    transed_env["trans_content"] = await self._request_llm_for_trans_with_terms(pm.env_system_prompt_with_dict,
                                                                                            env["content"],
                                                                                            fail_part=placeholder,
                                                                                            type="env",
                                                                                            session=session)
                else:
                    transed_env["trans_content"] = env["content"]

            if env["need_trans"]:
                try:
                    if self.update_term == True:
                        src_text = self._extract_text_from_tex(transed_env["content"])
                        tgt_text = self._extract_text_from_tex(transed_env["trans_content"])
                        text = await self._request_llm_for_extract_terms(pm.extract_terminology_system_prompt,
                                                                src_text,
                                                                tgt_text,
                                                                session=session
                                                                )

                            # self._updated_term_dict(term_text)
                        self._updated_term_dict_v2(text)
                except Exception as e:
                    return transed_env

        elif self.trans_mode == "plain":
            if env["need_trans"]:
                transed_env["trans_content"] = await self._request_llm_for_trans(pm.env_system_prompt,
                                                            env["content"],
                                                            fail_part=placeholder,
                                                            type="env",
                                                            session=session
                                                            )
            else:
                transed_env["trans_content"] = env["content"]

        return transed_env

    async def _request_llm_for_trans(self,
                                     system_prompt: str,
                                     text: str,
                                     fail_part: str,
                                     type: str,
                                     session: aiohttp.ClientSession) -> str:
        
        payload = {
            "model": f"{self.model}",
            "messages": [
                {"role": "system", "content": f"{system_prompt}"},
                {"role": "user", "content": f"{text}"}
            ],
            "temperature": 0.7,
            "max_new_tokens": 8192
        }

        headers = {
            "Authorization": f"Bearer {self.API_KEY}",
            "Content-Type": "application/json"
        }

        for attempt in range(1, 4):
            try:
                async with session.post(self.base_url, json=payload, headers=headers, timeout=100) as response:
                    response.raise_for_status()
                    result = await response.json()
                    return result["choices"][0]["message"]["content"].strip()

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < 3:
                    await asyncio.sleep(5)
                else:
                    self.have_fail_parts = True
                    if type == 'sec':
                        self.fail_section_nums.append(fail_part)
                    elif type == 'cap':
                        self.fail_caption_phs.append(fail_part)
                    else:
                        self.fail_env_phs.append(fail_part)

                    print(f"Failed to translate text, return original text: {fail_part}. {e}")
                    return text

    async def _request_llm_for_trans_with_terms(self,
                                          system_prompt: str,
                                          text: str,
                                          fail_part: str,
                                          type: str,
                                          session: aiohttp.ClientSession) -> str:

        payload = {
            "model": f"{self.model}",
            "messages": [
                {
                    "role": "system",
                    "content": f"{system_prompt}\nWhen translating, you must strictly use the following glossary for substitution. This is the highest priority rule to ensure the consistency of terms throughout the text.\n<Glossary>:\n{self.term_dict}\nNow, please translate the following new paragraph. Maintain the terminology from the glossary provided."
                },
                {
                    "role": "user",
                    "content": f"[Current LaTeX Paragraph]:\n{text}"
                }
            ],
            "temperature": 0.7,
            # "max_length": 100000,
            "max_new_tokens": 8192
        }

        headers = {
            "Authorization": f"Bearer {self.API_KEY}",
            "Content-Type": "application/json"
        }

        for attempt in range(1, 4):
            try:
                async with session.post(self.base_url, json=payload, headers=headers, timeout=100) as response:
                    response.raise_for_status()
                    result = await response.json()
                    return result["choices"][0]["message"]["content"].strip()

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < 3:
                    await asyncio.sleep(5)
                else:
                    self.have_fail_parts = True
                    if type == 'sec':
                        self.fail_section_nums.append(fail_part)
                    elif type == 'cap':
                        self.fail_caption_phs.append(fail_part)
                    else:
                        self.fail_env_phs.append(fail_part)

                    print(f"Failed to translate text, return original text: {fail_part}. {e}")

                    return text

    async def _request_llm_for_retrans_error_parts(self,
                                                   system_prompt: str,
                                                   part: Dict[str, Any],
                                                   error_message: str,
                                                   fail_part: str,
                                                   type: str,
                                                   session: aiohttp.ClientSession) -> str:

        user_prompt = self._build_retranslation_user_prompt(part, error_message)
        system_content = str(system_prompt)
        if self._should_use_terms_prompt():
            system_content = (
                f"{system_content}\n"
                "When translating, you must strictly use the following glossary for substitution. "
                "This is the highest priority rule to ensure the consistency of terms throughout the text.\n"
                f"<Glossary>:\n{self.term_dict}\n"
                "Now, please translate the following new paragraph. Maintain the terminology from the glossary provided."
            )

        payload = {
            "model": f"{self.model}",
            "messages": [
                {
                    "role": "system",
                    "content": system_content
                },
                {
                    "role": "user",
                    "content": f"{user_prompt}"
                }
            ],
            "temperature": 0.7,
            # "max_length": 100000,
            "max_new_tokens": 8192
        }

        headers = {
            "Authorization": f"Bearer {self.API_KEY}",
            "Content-Type": "application/json"
        }

        for attempt in range(1, 4):
            try:
                async with session.post(self.base_url, json=payload, headers=headers, timeout=100) as response:
                    response.raise_for_status()
                    result = await response.json()
                    return result["choices"][0]["message"]["content"].strip()

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                # print(f"Warning: request {attempt} failed for {fail_part}: {e}")
                if attempt < 3:
                    await asyncio.sleep(5)
                else:
                    self.have_fail_parts = True
                    if type == 'sec':
                        self.fail_section_nums.append(fail_part)
                    elif type == 'cap':
                        self.fail_caption_phs.append(fail_part)
                    else:
                        self.fail_env_phs.append(fail_part)

                    print(f"Failed to translate text, return original text: {fail_part}. {e}")
                    return part["trans_content"]

    def _build_retranslation_user_prompt(self, part: Dict[str, Any], error_message: str) -> str:
        diagnostics = self._build_error_diagnostics(part, error_message)
        return (
            f"[Original]:\n{part['content']}\n"
            f"[Translation]:\n{part['trans_content']}\n"
            f"[Error]:\n{error_message}\n"
            f"[Concrete Fix Checklist]:\n{diagnostics}"
        )

    def _build_error_diagnostics(self, part: Dict[str, Any], error_message: str) -> str:
        diagnostics = []
        command_errors = re.findall(
            r"'(\\[^']+)'\s+—\s+expected\s+(\d+),\s+found\s+(\d+)",
            error_message,
        )
        for command, expected, found in command_errors:
            diagnostics.append(
                f"- Preserve command `{command}`: source count={expected}, translation count={found}."
            )
            source_occurrences = self._format_command_occurrences(
                "Source occurrences", part.get("content", ""), command
            )
            translation_occurrences = self._format_command_occurrences(
                "Translation occurrences", part.get("trans_content", ""), command
            )
            diagnostics.extend([source_occurrences, translation_occurrences])

        if "Brackets error" in error_message:
            diagnostics.append(
                "- Fix only the reported bracket mismatch. Keep LaTeX optional labels such as "
                r"`\item[...]` structurally valid and do not add unmatched text parentheses."
            )

        if "Missing placeholders" in error_message or "Extra placeholders" in error_message:
            diagnostics.append(
                "- Match every placeholder in [Original] exactly once in the corrected translation."
            )

        if not diagnostics:
            diagnostics.append("- Apply the [Error] details exactly and preserve all LaTeX syntax.")

        diagnostics.append(
            "- Return the full corrected translation, not a patch or explanation."
        )
        return "\n".join(diagnostics)

    def _format_command_occurrences(self, title: str, text: str, command: str) -> str:
        snippets = []
        for idx, match in enumerate(re.finditer(re.escape(command), text), start=1):
            start = max(0, match.start() - 40)
            end = min(len(text), match.end() + 80)
            snippet = text[start:end].replace("\n", " ")
            snippets.append(f"  {idx}. ...{snippet}...")
            if idx >= 5:
                break

        if not snippets:
            return f"{title}:\n  none"
        return f"{title}:\n" + "\n".join(snippets)

    async def _request_llm_for_extract_terms(self, system_prompt, src, tgt,
                                       session: aiohttp.ClientSession) -> str:
        source_label = self._source_language_label()
        target_label = self._target_language_label()

        payload = {
            "model": f"{self.model}",
            "messages": [
                {
                    "role": "system", 
                    "content": f"{system_prompt}"
                },
                {
                    "role": "user", 
                    "content": f"<{source_label} source>\n{src}\n<{target_label} translation>\n{tgt}"
                }
            ],
            "temperature": 0.7,
            # "max_length": 100000,
            # "max_tokens": 50
        }

        headers = {
            "Authorization": f"Bearer {self.API_KEY}",
            "Content-Type": "application/json"
        }

        for attempt in range(1, 4):
            try:
                async with session.post(self.base_url, json=payload, headers=headers, timeout=100) as response:
                    response.raise_for_status()
                    result = await response.json()
                    return result["choices"][0]["message"]["content"].strip()

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < 3:
                    await asyncio.sleep(5)
                else:
                    print("Warning: failed to extract terms, set N/A.")
                    return "N/A"

    def _request_llm_for_summary(self, system_prompt: str, text: str) -> str:
        """
        Requests the LLM to summarize the given text.
        """
        payload = {
            "model": f"{self.model}",
            "messages": [
                {
                    "role": "system", 
                    "content": f"{system_prompt}"
                },
                {
                    "role": "user", 
                    "content": f"<Text to summarize>:\n{text}\n<Summary>:\n"
                }
            ],
            "temperature": 0.7,
            # "max_length": 100000,
            "max_new_tokens": 8192
        }

        headers = {
            "Authorization": f"Bearer {self.API_KEY}",
            "Content-Type": "application/json"
        }
        
        for attempt in range(1, 4):
            try:
                response = requests.post(self.base_url, json=payload, headers=headers, timeout=100)
                response.raise_for_status()  
                result = response.json()
                return result["choices"][0]["message"]["content"].strip()
            except requests.exceptions.RequestException as e:
                if attempt < 3:
                    print(f"{e}")
                    time.sleep(3)  
                else:
                    print("Warning: failed to summarize text, set N/A.")
                    return "N/A"

    def _request_llm_for_refine_summary(self, system_prompt: str, text: str, sum: str) -> str:
        """
        Requests the LLM to refine the given summary.
        """
        payload = {
            "model": f"{self.model}",
            "messages": [
                {
                    "role": "system", 
                    "content": f"{system_prompt}"
                },
                {
                    "role": "user", 
                    "content": f"<prev_summary>:\n{sum}\n<new_section>:\n{text}\n<refined_summary>:\n"
                }
            ],
            "temperature": 0.7,
            # "max_length": 100000,
            "max_new_tokens": 8192
        }

        headers = {
            "Authorization": f"Bearer {self.API_KEY}",
            "Content-Type": "application/json"
        }
        
        for attempt in range(1, 4):
            try:
                response = requests.post(self.base_url, json=payload, headers=headers, timeout=100)
                response.raise_for_status()  
                result = response.json()
                return result["choices"][0]["message"]["content"].strip()
            except requests.exceptions.RequestException as e:
                if attempt < 3:
                    print(f"{e}")
                    time.sleep(3)  
                else:
                    print("Warning: failed to refine summary, set N/A.")
                    return "N/A"

    def _source_language_label(self) -> str:
        return pm.language_label(self.config.get("source_language", "en"))

    def _target_language_label(self) -> str:
        return pm.language_label(self.config.get("target_language", "ch"))

    def _uses_default_english_chinese_terms(self) -> bool:
        return (
            self._source_language_label().lower() == "english"
            and self._target_language_label().lower() == "chinese"
        )

    def _updated_term_dict(self, text: str) -> None:
        """
        Updates the term dictionary with new terms.
        """
        pattern = r'"([^"]+)"\s*-\s*"([^"]+)"'
        matches = re.findall(pattern, text)

        seen_lower = {k.lower() for k in self.term_dict}
        
        for en, zh in matches:
            en_lower = en.lower()
            if en_lower not in seen_lower:
                self.term_dict[en] = zh  
                seen_lower.add(en_lower)

        self.save_file(Path(self.output_dir, "term_dict.json"), "json", self.term_dict)

    def _updated_term_dict_v2(self, text: str) -> None:

        new_term_dict = {}
        lines = text.split('\n')[1:]
        for line in lines:
            line = line.strip()
            if not line:
                continue  

            match = re.match(r'^"(.+?)"\s*-\s*"(.+?)"$', line)
            if match:
                english = match.group(1)
                chinese = match.group(2)
                new_term_dict[english] = chinese

        for en, zh in new_term_dict.items():
            if en not in self.term_dict:
                self.term_dict[en] = zh

    def _process_latex_to_eva(self, latex_code):
        latex_code = replace_href(latex_code)
        latex_code = replace_includegraphics(latex_code)
        return latex_code

    def _extract_text_from_tex(self, tex):
        # convert = CustomLatexNodes2Text()
        # text = convert.latex_to_text(tex)
        tex = self._process_latex_to_eva(tex)
        text = LatexNodes2Text().latex_to_text(tex)
        text = delete_ph(text)
        return text
    
    def _merge_with_prev_sections(self, sections: list[dict], idx: int) -> str:
        """
        Merge content of current section with previous two sections (if valid).
        Ignore sections whose 'section' field is "-1" or "0".

        Parameters:
            sections (list of dict): A list of sections, each with keys "section" and "content".
            idx (int): The index of the current section in the list.

        Returns:
            str: The merged content string.
        """
        if not (0 <= idx < len(sections)):
            raise IndexError("Index out of range.")

        merged_content = []
        merged_trans_content = []

        # Check second previous section
        # if idx >= 2:
        #     sec = sections[idx - 2]
        #     if sec["section"] not in {"-1", "0"}:
        #         try:
        #             content = self._extract_text_from_tex(sec["content"])
        #             transed_content = self._extract_text_from_tex(sec["trans_content"])
        #             merged_content.append(content)
        #             merged_trans_content.append(transed_content)
        #         except Exception as e:
        #             pass
                

        # Check first previous section
        if idx >= 1:
            sec = sections[idx - 1]
            if sec["section"] not in {"-1", "0"}:
                try:
                    content = self._extract_text_from_tex(sec["content"])
                    transed_content = self._extract_text_from_tex(sec["trans_content"])
                    merged_content.append(content)
                    merged_trans_content.append(transed_content)
                except Exception as e:
                    pass

        # Always include current section
        try:
            content = self._extract_text_from_tex(sections[idx]["content"])
            transed_content = self._extract_text_from_tex(sections[idx]["trans_content"])
            merged_content.append(content)
            merged_trans_content.append(transed_content)
        except Exception as e:
            pass

        return "\n".join(merged_content)

    def build_term_dict(self):
        placeholder_terms = {
            key: value
            for key, value in self.term_dict.items()
            if self._is_placeholder_term(key, value)
        }
        self.term_dict = dict(placeholder_terms)
        self._project_terms_loaded = False

        source_language = self.config.get("source_language", "en")
        user_terms = {}
        project_terms = {}
        default_terms = {}

        if self.user_term:
            user_result = load_term_csv(Path(self.user_term), source_language=source_language)
            for warning in user_result.warnings:
                print(f"Warning: {warning}")
            user_terms = user_result.terms

        if self.output_dir:
            terms_path = project_terms_path(Path(self.output_dir))
            if terms_path.exists():
                project_result = load_term_csv(terms_path, source_language=source_language)
                for warning in project_result.warnings:
                    print(f"Warning: {warning}")
                project_terms = project_result.terms
                self._project_terms_loaded = bool(project_terms)

        if self._uses_default_english_chinese_terms():
            arxiv_id = os.path.basename(self.project_dir or "")
            category_map = self.category or {}
            if category_map.get(arxiv_id):
                term_dict_loaded = False
                for category in category_map[arxiv_id]:
                    file_path = os.path.join("terms", f"{category}.csv")
                    try:
                        df = pd.read_csv(file_path, header=None, names=["Source Term", "Target Translation"])
                        default_terms.update(zip(df["Source Term"], df["Target Translation"]))
                        term_dict_loaded = True
                    except FileNotFoundError:
                        continue
                if not term_dict_loaded:
                    default_terms.update(self._load_default_terms_file())
            else:
                default_terms.update(self._load_default_terms_file())

        self.term_dict.update(merge_term_pairs(
            user_terms.items(),
            project_terms.items(),
            default_terms.items(),
            source_language=source_language,
        ))

    def _load_default_terms_file(self) -> Dict[str, str]:
        try:
            df = pd.read_csv("terms/default.csv", header=None, names=["Source Term", "Target Translation"])
            return dict(zip(df["Source Term"], df["Target Translation"]))
        except FileNotFoundError as e:
            print(f"Error: Default terminology file not found: {e}")
            return {}

    def _should_use_terms_prompt(self) -> bool:
        return self.trans_mode == "terms" or self._project_terms_loaded

    def _is_placeholder_term(self, key: str, value: str) -> bool:
        return key == value and bool(re.fullmatch(r"<PLACEHOLDER_[^>]+>", key))

    def add_placeholder(self):

        # Add placeholders from caption, env, input, and newcommand to the vocabulary
        caption_path = os.path.join(self.output_dir, "captions_map.json")
        input_path = os.path.join(self.output_dir, "inputs_map.json")
        env_path = os.path.join(self.output_dir, "envs_map.json")
        command_path = os.path.join(self.output_dir, "newcommands_map.json")

        placeholder_list = []

        with open(input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for item in data:
            if "begin" in item:
                placeholder_list.append(item["begin"])
            if "end" in item:
                placeholder_list.append(item["end"])

        with open(env_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for item in data:
            if "placeholder" in item:
                placeholder_list.append(item["placeholder"])

        with open(caption_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for item in data:
            if "placeholder" in item:
                placeholder_list.append(item["placeholder"])

        with open(command_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for item in data:
            if "placeholder" in item:
                placeholder_list.append(item["placeholder"])

        for item in placeholder_list:
            self.term_dict[item] = item



