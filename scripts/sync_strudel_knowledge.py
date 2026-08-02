#!/usr/bin/env python3
"""Build the checked-in Strudel knowledge corpus from pinned upstream sources."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any


REPL_VERSION = "1.3.0"
REPL_TAG = f"@strudel/repl@{REPL_VERSION}"
REPL_COMMIT = "f610965f4332837febe45743105da170e8b331ed"
REFERENCE_VERSION = "1.2.2"
SOURCE_ARCHIVE_URL = f"https://codeberg.org/uzu/strudel/archive/{REPL_TAG}.tar.gz"
REFERENCE_ARCHIVE_URL = (
    f"https://registry.npmjs.org/@strudel/reference/-/reference-{REFERENCE_VERSION}.tgz"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "backend" / "app" / "knowledge" / "strudel"
TUTORIAL_PATHS = (
    "website/src/pages/learn",
    "website/src/pages/workshop",
    "website/src/pages/recipes",
)
_FRONTMATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)
_IMPORT_LINE = re.compile(r"^import\s+.*?;\s*$", re.MULTILINE)
_MINI_REPL = re.compile(r"<MiniRepl\b(?P<attrs>.*?)\s*/>", re.DOTALL)
_JSDOC = re.compile(r"<JsDoc\b(?P<attrs>.*?)\s*/>", re.DOTALL)
_NAME_ATTRIBUTE = re.compile(r'\bname\s*=\s*["\']([^"\']+)["\']')
_TEMPLATE_TUNE = re.compile(r"\btune\s*=\s*\{\s*`(.*?)`\s*\}", re.DOTALL)
_STRING_TUNE = re.compile(r'\btune\s*=\s*\{?\s*["\'](.*?)["\']\s*\}?', re.DOTALL)
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_HTML_TAG = re.compile(r"<[^>]+>")
_JSX_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_NON_SLUG = re.compile(r"[^a-z0-9._-]+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, help="Extracted Strudel repository root")
    parser.add_argument("--reference-module", type=Path, help="Built @strudel/reference index.mjs")
    parser.add_argument("--license-file", type=Path, help="Upstream AGPL license file")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="strudel-knowledge-") as temporary:
        temporary_dir = Path(temporary)
        source_dir = args.source_dir or _download_and_extract(
            SOURCE_ARCHIVE_URL,
            temporary_dir / "strudel-source.tar.gz",
            temporary_dir / "strudel-source",
        )
        reference_root = None
        reference_module = args.reference_module
        if reference_module is None:
            reference_root = _download_and_extract(
                REFERENCE_ARCHIVE_URL,
                temporary_dir / "strudel-reference.tgz",
                temporary_dir / "strudel-reference",
            )
            reference_module = reference_root / "dist" / "index.mjs"

        reference = _load_reference(reference_module)
        reference_documents, reference_by_name = _reference_documents(reference)
        tutorial_documents = _tutorial_documents(source_dir, reference_by_name)
        documents = sorted((*tutorial_documents, *reference_documents), key=lambda item: item["id"])
        corpus = {"schemaVersion": 1, "documents": documents}
        corpus_text = json.dumps(corpus, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

        output_dir = args.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "corpus.json").write_text(corpus_text, encoding="utf-8")
        counts = {
            kind: sum(1 for document in documents if document["kind"] == kind)
            for kind in ("tutorial", "reference")
        }
        manifest = {
            "schemaVersion": 1,
            "replVersion": REPL_VERSION,
            "replTag": REPL_TAG,
            "upstreamCommit": REPL_COMMIT,
            "referenceVersion": REFERENCE_VERSION,
            "sourceRepository": "https://codeberg.org/uzu/strudel",
            "license": "AGPL-3.0-or-later",
            "documentCounts": counts,
            "corpusBytes": len(corpus_text.encode("utf-8")),
            "corpusSha256": hashlib.sha256(corpus_text.encode("utf-8")).hexdigest(),
        }
        (output_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        license_file = args.license_file or (reference_root / "LICENSE" if reference_root else None)
        if license_file and license_file.is_file():
            shutil.copyfile(license_file, output_dir / "LICENSE.strudel")

    print(
        f"wrote {len(documents)} documents "
        f"({counts['tutorial']} tutorial, {counts['reference']} reference) to {output_dir}"
    )


def _download_and_extract(url: str, archive_path: Path, destination: Path) -> Path:
    print(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=60) as response, archive_path.open("wb") as output:
        shutil.copyfileobj(response, output)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(destination, filter="data")
    roots = [item for item in destination.iterdir() if item.is_dir()]
    if len(roots) != 1:
        raise RuntimeError(f"Expected one archive root in {destination}")
    return roots[0]


def _load_reference(module_path: Path) -> dict[str, Any]:
    module_path = module_path.resolve()
    script = """
import { pathToFileURL } from 'node:url';
const module = await import(pathToFileURL(process.argv[1]).href);
process.stdout.write(JSON.stringify(module.reference));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(module_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict) or not isinstance(value.get("docs"), list):
        raise RuntimeError("@strudel/reference did not export the expected docs collection")
    return value


def _reference_documents(
    reference: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    documents: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    for entry in reference["docs"]:
        if not isinstance(entry, dict):
            continue
        name = _clean_scalar(entry.get("name"))
        description = _html_text(entry.get("description"))
        if not name or name.startswith("_") or not description:
            continue
        aliases = sorted(
            {_clean_scalar(alias) for alias in entry.get("synonyms", []) if _clean_scalar(alias)},
            key=str.casefold,
        )
        names = [name, *aliases]
        content = _render_reference(entry, name, aliases, description)
        identifier = _unique_id(f"reference:{_slug(name)}", seen_ids)
        meta = entry.get("meta") if isinstance(entry.get("meta"), dict) else {}
        filename = _clean_scalar(meta.get("filename"))
        document = {
            "id": identifier,
            "kind": "reference",
            "title": name,
            "topic": _reference_topic(filename),
            "path": f"reference/{name}",
            "names": names,
            "tags": sorted({"api", _reference_topic(filename), filename} - {""}),
            "content": content,
            "sourceUrl": "https://www.npmjs.com/package/@strudel/reference",
        }
        documents.append(document)
        for candidate in names:
            by_name.setdefault(candidate.casefold(), entry)
        longname = _clean_scalar(entry.get("longname"))
        if longname:
            by_name.setdefault(longname.casefold(), entry)
    return documents, by_name


def _tutorial_documents(
    source_dir: Path,
    reference_by_name: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for relative_root in TUTORIAL_PATHS:
        root = source_dir / relative_root
        for path in sorted(root.glob("*.mdx")):
            relative_path = path.relative_to(source_dir).as_posix()
            route_parts = relative_path.removeprefix("website/src/pages/").removesuffix(".mdx").split("/")
            topic = route_parts[-1]
            source_url = f"https://strudel.cc/{'/'.join(route_parts)}/"
            markdown = _normalize_mdx(path.read_text(encoding="utf-8"), reference_by_name)
            for heading_path, body in _split_sections(markdown):
                title = heading_path[-1]
                identifier = _unique_id(
                    f"tutorial:{'/'.join(route_parts)}#{_slug('/'.join(heading_path))}",
                    seen_ids,
                )
                names = sorted(set(_code_names(f"{title}\n{body}")), key=str.casefold)
                documents.append(
                    {
                        "id": identifier,
                        "kind": "tutorial",
                        "title": title,
                        "topic": topic,
                        "path": " / ".join(heading_path),
                        "names": names,
                        "tags": sorted({route_parts[0], topic, *names}, key=str.casefold),
                        "content": f"# {' / '.join(heading_path)}\n\n{body}".strip(),
                        "sourceUrl": source_url,
                    }
                )
    return documents


def _normalize_mdx(text: str, reference_by_name: dict[str, dict[str, Any]]) -> str:
    text = _FRONTMATTER.sub("", text)
    text = _IMPORT_LINE.sub("", text)

    def replace_repl(match: re.Match[str]) -> str:
        tune = _extract_tune(match.group("attrs"))
        return f"\n```js\n{tune.strip()}\n```\n" if tune.strip() else "\n"

    def replace_jsdoc(match: re.Match[str]) -> str:
        name_match = _NAME_ATTRIBUTE.search(match.group("attrs"))
        if not name_match:
            return "\n"
        name = name_match.group(1)
        entry = reference_by_name.get(name.casefold())
        if not entry:
            return f"\nFunction reference: `{name}`.\n"
        aliases = [
            _clean_scalar(alias)
            for alias in entry.get("synonyms", [])
            if _clean_scalar(alias)
        ]
        return "\n" + _render_reference(entry, name, aliases, _html_text(entry.get("description"))) + "\n"

    text = _MINI_REPL.sub(replace_repl, text)
    text = _JSDOC.sub(replace_jsdoc, text)
    text = text.replace("<br />", "\n").replace("<br/>", "\n")
    text = _JSX_TAG.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_tune(attributes: str) -> str:
    template = _TEMPLATE_TUNE.search(attributes)
    if template:
        return template.group(1).replace(r"\*", "*").replace(r"\`", "`")
    string = _STRING_TUNE.search(attributes)
    if string:
        return html.unescape(string.group(1))
    return ""


def _split_sections(markdown: str) -> list[tuple[list[str], str]]:
    matches = list(_HEADING.finditer(markdown))
    if not matches:
        return []
    sections: list[tuple[list[str], str]] = []
    hierarchy: list[str] = []
    for index, match in enumerate(matches):
        level = len(match.group(1))
        title = _plain_heading(match.group(2))
        hierarchy = hierarchy[: level - 1]
        hierarchy.append(title)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[match.end() : end].strip()
        if body:
            sections.append((hierarchy.copy(), body))
    return sections


def _render_reference(entry: dict[str, Any], name: str, aliases: list[str], description: str) -> str:
    parts = [description]
    if aliases:
        parts.append("Aliases: " + ", ".join(f"`{alias}`" for alias in aliases))
    parameters: list[str] = []
    for parameter in entry.get("params", []):
        if not isinstance(parameter, dict):
            continue
        parameter_name = _clean_scalar(parameter.get("name"))
        type_names = parameter.get("type", {}).get("names", []) if isinstance(parameter.get("type"), dict) else []
        type_label = " | ".join(str(item) for item in type_names if item)
        parameter_description = _html_text(parameter.get("description"))
        label = f"- `{parameter_name}`"
        if type_label:
            label += f" ({type_label})"
        if parameter_description:
            label += f": {parameter_description}"
        parameters.append(label)
    if parameters:
        parts.append("Parameters:\n" + "\n".join(parameters))
    examples = [str(example).strip() for example in entry.get("examples", []) if str(example).strip()]
    if examples:
        parts.append("Examples:\n" + "\n\n".join(f"```js\n{example}\n```" for example in examples))
    return "\n\n".join(part for part in parts if part).strip()


def _html_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"</(?:p|li|div|pre|h\d)>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = _HTML_TAG.sub("", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_scalar(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _plain_heading(value: str) -> str:
    value = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", value)
    value = value.replace("`", "").strip()
    return _HTML_TAG.sub("", value).strip()


def _code_names(value: str) -> list[str]:
    return re.findall(r"(?<![\w-])([A-Za-z_][A-Za-z0-9_]*)(?=\s*\()", value)


def _reference_topic(filename: str) -> str:
    mapping = {
        "controls.mjs": "controls",
        "pattern.mjs": "patterns",
        "signal.mjs": "signals",
        "dough.mjs": "audio",
        "pianoroll.mjs": "visuals",
        "scope.mjs": "visuals",
        "pitchwheel.mjs": "visuals",
        "spiral.mjs": "visuals",
        "spectrum.mjs": "visuals",
        "tonal.mjs": "tonal",
    }
    return mapping.get(filename, Path(filename).stem or "reference")


def _slug(value: str) -> str:
    slug = _NON_SLUG.sub("-", value.casefold()).strip("-")
    return slug or "section"


def _unique_id(base: str, seen: set[str]) -> str:
    if base not in seen:
        seen.add(base)
        return base
    index = 2
    while f"{base}-{index}" in seen:
        index += 1
    value = f"{base}-{index}"
    seen.add(value)
    return value


if __name__ == "__main__":
    main()
