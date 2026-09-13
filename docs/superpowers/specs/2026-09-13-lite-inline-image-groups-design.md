# Lite Inline Image Groups Design

## Goal

Prevent consecutive standalone images extracted by MinerU from consuming one
full-width paragraph each in the lite engine's generated PDF.

## Behavior

- Process the translated Markdown immediately before it is written to
  `translated.md`.
- Recognize only consecutive lines containing exactly one standalone Markdown
  image (`![alt](destination)`), with optional surrounding whitespace.
- Preserve each image's alt text and destination byte-for-byte.
- Emit images from each run in rows of at most three images.
- Add a Pandoc image width attribute of `0.32\\linewidth` to grouped images so
  three images fit on one line in the XeLaTeX PDF.
- Any non-image line, heading, paragraph, blank line, or image syntax with
  trailing content ends the current run.
- Runs containing one image remain unchanged; source Markdown is never
  rewritten.

## Components

`src/engines/lite_markdown.py` will expose a pure `group_standalone_images`
helper. `MarkdownTranslatorAgent.execute` will invoke it on the rebuilt
translated Markdown before the temporary output file is written.

## Testing

Unit tests will cover one image, three images, four images producing two rows,
run termination by prose/blank lines, preservation of alt text and paths, and
idempotence for already grouped output.
