from typing import Dict, Any, List, Optional
from src.agents.tool_agents.base_tool_agent import BaseToolAgent
from src.validation_policy import ValidationPolicy
# from base_tool_agent import BaseToolAgent
from pathlib import Path
from collections import Counter
from pylatexenc.latexwalker import LatexWalker
import sys
import os
import re

base_dir = os.getcwd()
sys.path.append(base_dir)


class ValidatorAgent(BaseToolAgent):
    def __init__(self, 
                 config: Dict[str, Any],
                 project_dir: str = None,
                 output_dir: str = None,
                 ):
        super().__init__(agent_name="ValidatorAgent", config=config)
        self.config = config
        self.policy = ValidationPolicy.from_config(config or {})
        self.project_dir = project_dir
        self.output_dir = output_dir

    def execute(self, errors_report : Optional[List[Dict]]=None) -> List[Dict]:

        self.log(f"🤖💬 Start validating for project...⏳: {os.path.basename(self.project_dir)}.")
        sections = self.read_file(Path(self.output_dir, "sections_map.json"), "json")
        captions = self.read_file(Path(self.output_dir, "captions_map.json"), "json")
        envs = self.read_file(Path(self.output_dir, "envs_map.json"), "json")

        if errors_report is None:
            parts_need_val = self._extract_parts_need_validate(secs=sections, # secs caps envs
                                                               caps=captions,
                                                               envs=envs)
        else:
            parts_need_val = self._extract_parts_from_report(secs=sections, 
                                                               caps=captions,
                                                               envs=envs,
                                                               errors_report=errors_report)
        errors_report = []
        for part in parts_need_val:
            error_report = self._validate(part)
            if error_report:
                errors_report.append(error_report)
        self.save_file(Path(self.output_dir, "errors_report.json"), "json", errors_report)

        self.log(f"✅ Verification Complete for {os.path.basename(self.project_dir)}, remaining Errors: {len(errors_report)}.")
        return errors_report

    def _make_issue(self, issue_type: str, message: str, severity: str, retryable: bool) -> Dict[str, Any]:
        return {"type": issue_type, "severity": severity, "retryable": retryable, "message": message}

    def _make_policy_issue(self, issue_type: str, message: str) -> Dict[str, Any]:
        return self._make_issue(
            issue_type=issue_type,
            message=message,
            severity=self.policy.issue_severity(issue_type),
            retryable=self.policy.issue_retryable(issue_type),
        )

    def _highest_severity(self, issues: List[Dict[str, Any]]) -> str:
        if any(issue["severity"] == "error" for issue in issues):
            return "error"
        return "warning"

    def _is_retryable(self, issues: List[Dict[str, Any]]) -> bool:
        return any(issue.get("retryable", False) for issue in issues)

    def _messages_for_type(self, issues: List[Dict[str, Any]], issue_type: str) -> List[str]:
        return [issue["message"] for issue in issues if issue["type"] == issue_type]

    def _validate(self, part :Dict[str, Any]) -> Dict[str, Any]:
        issues = []
        issues.extend(self._validate_command(part) or [])
        issues.extend(self._validate_placeholder(part) or [])
        issues.extend(self._validate_closed_brackets(part) or [])

        if not issues:
            return None

        error_report = {
            "severity": self._highest_severity(issues),
            "retryable": self._is_retryable(issues),
            "issues": issues,
        }

        if "section" in part:
            error_report["part"] = "sec"
            error_report["num_or_ph"] = part["section"]
        elif "env_name" in part:
            error_report["part"] = "env"
            error_report["num_or_ph"] = part["placeholder"]
        elif "cap_type" in part:
            error_report["part"] = "cap"
            error_report["num_or_ph"] = part["placeholder"]

        command_messages = self._messages_for_type(issues, "command_mismatch")
        placeholder_messages = self._messages_for_type(issues, "placeholder_mismatch")
        bracket_messages = self._messages_for_type(issues, "bracket_mismatch")

        if command_messages:
            error_report["command_error"] = "LaTeX command translation error or is missing:\n" + "\n".join(command_messages)
        if placeholder_messages:
            error_report["ph_error"] = "\n".join(placeholder_messages)
        if bracket_messages:
            error_report["bracket_error"] = "Brackets error:\n" + "\n".join(bracket_messages)

        return error_report

    def _validate_command(self, part :Dict[str, Any])-> Optional[List[Dict[str, Any]]]:
        content = part.get("content", "")
        trans = part.get("trans_content", "")

        # src_counter = self._extract_latex_elements_with_counts(content)
        # trans_counter = self._extract_latex_elements_with_counts(trans)
        src_counter = self.extract_command_counts(content)
        trans_counter = self.extract_command_counts(trans)
        if src_counter == trans_counter:
            return None

        issues = []
        for elem, count in src_counter.items():
            aliases = self._equivalent_commands(elem)
            found = sum(trans_counter.get(alias, 0) for alias in aliases)
            if found < count:
                issues.append(self._make_policy_issue(
                    issue_type="command_mismatch",
                    message=f"'{elem}' — expected {count}, found {found}",
                ))

        return issues or None

    def _equivalent_commands(self, command: str) -> set[str]:
        equivalent_groups = [
            {"\\bf", "\\textbf"},
        ]
        for group in equivalent_groups:
            if command in group:
                return group
        return {command}

    def _validate_placeholder(self, part :Dict[str, Any])-> Optional[List[Dict[str, Any]]]:

        original_placeholders = self._extract_placeholders(part["content"])
        translated_placeholders = self._extract_placeholders(part["trans_content"])
        missing = original_placeholders - translated_placeholders
        extra = translated_placeholders - original_placeholders
        issues = []
        if missing:
            issues.append(self._make_policy_issue(
                issue_type="placeholder_mismatch",
                message=f"Missing placeholders: {', '.join(sorted(missing))} translation error or is missing!",
            ))
        if extra:
            issues.append(self._make_policy_issue(
                issue_type="placeholder_mismatch",
                message=f"Extra placeholders: {', '.join(sorted(extra))} translation error or is redundant",
            ))
        return issues or None
        
    def _validate_closed_brackets(self, part: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:

        content = part.get("content", "")
        trans_content = part.get("trans_content", "")
        org_errors = self._find_brackets_errors(content, org=1)
        errors = self._find_brackets_errors(trans_content)

        if errors and not org_errors:
            return [self._make_policy_issue(
                issue_type="bracket_mismatch",
                message="\n".join(errors),
            )]
        return None
        
    def _find_brackets_errors(self, content, org=None):

        if org:
            bracket_pairs = {'[': ']', '{': '}'}    
        else:
            content = self._mask_item_optional_labels(content)
            bracket_pairs = {'(': ')', '（': '）', '[': ']', '{': '}'}
        opening_brackets = set(bracket_pairs.keys())
        closing_brackets = set(bracket_pairs.values())

        stack = []
        errors = []
        for idx, char in enumerate(content):
            if char in opening_brackets:
                stack.append((char, idx))
            elif char in closing_brackets:
                if not stack:
                    fragment = content[max(0, idx - 10): idx + 10]
                    errors.append(f"Extra closing bracket '{char}' at position {idx}, context: {fragment}")
                else:
                    last_open, open_idx = stack.pop()
                    if bracket_pairs[last_open] != char:
                        fragment = content[open_idx: idx + 1]
                        errors.append(f"Bracket mismatch: '{last_open}' opened at {open_idx} does not match '{char}' at {idx}, fragment: {fragment}")

        # Any unmatched opening brackets left in stack
        for open_bracket, pos in stack:
            fragment = content[pos: pos + 20]
            errors.append(f"Unmatched opening bracket '{open_bracket}' at position {pos}, fragment: {fragment}")

        return errors

    def _mask_item_optional_labels(self, content: str) -> str:
        chars = list(content)
        item_pattern = re.compile(r"\\item\b")
        for match in item_pattern.finditer(content):
            idx = match.end()
            while idx < len(content) and content[idx].isspace():
                idx += 1
            if idx >= len(content) or content[idx] != "[":
                continue

            depth = 0
            pos = idx
            while pos < len(content):
                if content[pos] == "\\":
                    pos += 2
                    continue
                if content[pos] == "[":
                    depth += 1
                elif content[pos] == "]":
                    depth -= 1
                    if depth == 0:
                        for mask_pos in range(idx, pos + 1):
                            chars[mask_pos] = " "
                        break
                pos += 1

        return "".join(chars)

    def _extract_latex_elements_with_counts(self, content: str) -> Counter:
        elements = []

        elements += re.findall(r"\\begin\{.*?\}", content)
        elements += re.findall(r"\\end\{.*?\}", content)

        elements += re.findall(r"\\[a-zA-Z]+\*?", content)

        math_inline = re.findall(r"\$(.+?)\$", content, re.DOTALL)
        # math_display = re.findall(r"\\\[(.+?)\\\]", content, re.DOTALL)
        elements += [expr.strip() for expr in math_inline  if expr.strip()]

        return Counter(elements)
    
    def extract_command_counts(self, latex_code: str) -> Counter:
        walker = LatexWalker(latex_code)
        nodes, _, _ = walker.get_latex_nodes()
        counter = Counter()
        
        ignored_commands = {'eg', 'ie'}

        def recurse(nodes):
            for node in nodes:
                clsname = node.__class__.__name__

                if clsname == "LatexMacroNode":
                    macro_name = node.macroname

                    if macro_name in ignored_commands:
                        continue
                    if len(macro_name) == 1 and not macro_name.isalpha():
                        continue

                    command = f"\\{macro_name}"
                    counter[command] += 1

                    if node.nodeargd:
                        for arg in node.nodeargd.argnlist:
                            if arg is not None:
                                recurse([arg])

                elif clsname == "LatexEnvironmentNode":
                    env_name = node.environmentname
                    counter[f"\\begin{{{env_name}}}"] += 1
                    recurse(node.nodelist)
                    counter[f"\\end{{{env_name}}}"] += 1

                elif hasattr(node, 'nodelist') and node.nodelist:
                    recurse(node.nodelist)

        recurse(nodes)
        return counter

    def _extract_placeholders(self, content):
        input_pattern = re.compile(r"<PLACEHOLDER_[^>]+?_begin>|<PLACEHOLDER_[^>]+?_end>")
        placeholder_pattern_cap = re.compile(r"<PLACEHOLDER_CAP_\d+>")
        placeholder_pattern_env = re.compile(r"<PLACEHOLDER_ENV_\d+>")
        placeholders = set()
        for pattern in [input_pattern, placeholder_pattern_cap, placeholder_pattern_env]:
            placeholders.update(pattern.findall(content))
        return placeholders

    def _extract_parts_need_validate(self, secs, caps, envs):
        secs_need_val = [sec for sec in secs if sec["section"] != 0]
        caps_need_val = caps
        if envs:
            if "need_trans" in envs[0]:
                envs_need_val = [env for env in envs if env["need_trans"]]
            else:
                envs_need_val = [env for env in envs if env["content"] != env["trans_content"]]
        else:
            envs_need_val = []

        return secs_need_val + caps_need_val + envs_need_val
    
    def _extract_parts_from_report(
        self,
        secs: List[Dict],
        caps: List[Dict],
        envs: List[Dict],
        errors_report: List[Dict]) -> List[Dict]:

        section_lookup = {s["section"]: s for s in secs}
        caption_lookup = {c["placeholder"]: c for c in caps}
        environment_lookup = {e["placeholder"]: e for e in envs}
        
        parts_to_validate = []
        
        for error in errors_report:
            part_type = error.get("part")
            identifier = error.get("num_or_ph")
            
            if not part_type or not identifier:
                continue
                
            part = None
            if part_type == "sec":
                part = section_lookup.get(identifier)
            elif part_type == "cap":
                part = caption_lookup.get(identifier)
            elif part_type == "env":
                part = environment_lookup.get(identifier)
            
            if part:
                parts_to_validate.append(part)
                
        return parts_to_validate
    

# import toml
# import argparse
# from tqdm import tqdm
# from src.formats.latex.utils import get_profect_dirs


# parser = argparse.ArgumentParser()
# parser.add_argument("--config", type=str, default="config/default.toml")
# args = parser.parse_args()

# config = toml.load(args.config)
# dir = "D:\code\AutoLaTexTrans\outputs"
# projects = get_profect_dirs(dir)
# for project_dir in tqdm(projects, desc="Processing projects", unit="project"):
#     Validator = ValidatorAgent(config=config,
#                             project_dir=project_dir,
#                             output_dir=project_dir
#                             )
#     errors_report = Validator.execute()
#     if errors_report:
#         for error_report in errors_report:
#             error = ''
#             if "command_error" in error_report:
#                 error += error_report["command_error"] + '\n'
#             if "ph_error" in error_report:
#                 error += error_report["ph_error"] + '\n'
#             if "bracket_error" in error_report:
#                 error += error_report["bracket_error"] + '\n'
#             print(error_report["num_or_ph"])
#             print('\n')
#             print(error)
