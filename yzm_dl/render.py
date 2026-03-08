import html
import json
import os

from .common import (
    ensure_dir,
    guess_mime_type,
    html_to_text,
    normalize_notice_texts,
    ordered_slug,
    safe_relpath,
    write_text,
)


def build_video_section_html(video_files):
    if not video_files:
        return ""

    parts = ['<section class="lesson-videos">', "<h2>Videolar</h2>"]
    for index, video in enumerate(video_files, start=1):
        title = html.escape(video.get("title") or f"Video {index}")
        file_name = html.escape(video["file"])
        mime_type = guess_mime_type(video["file"])
        parts.extend(
            [
                '<figure class="lesson-video">',
                f"<figcaption>{title}</figcaption>",
                '<video controls preload="metadata">',
                f'<source src="{file_name}" type="{mime_type}">',
                f'<a href="{file_name}">{title}</a>',
                "</video>",
            ]
        )
        transcript_text = (video.get("transcript") or {}).get("text", "").strip()
        if transcript_text:
            parts.extend(
                [
                    '<section class="video-transcript">',
                    "<h3>Video Transcript</h3>",
                    f"<pre>{html.escape(transcript_text)}</pre>",
                    "</section>",
                ]
            )
        parts.append("</figure>")
    parts.append("</section>")
    return "\n".join(parts)


def build_materials_section_html(materials):
    links = materials.get("links", []) if materials else []
    if not links:
        return ""

    parts = ['<section class="lesson-materials">', "<h2>Materyaller</h2>", "<ul>"]
    for link in links:
        href = html.escape(link.get("href") or "")
        text = html.escape(link.get("text") or href or "Materyal")
        parts.append(f'<li><a href="{href}">{text}</a></li>')
    parts.extend(["</ul>", "</section>"])
    return "\n".join(parts)


def build_external_video_links_html(iframes):
    if not iframes:
        return ""

    parts = ['<section class="lesson-video-links">', "<h2>Harici Video Kaynaklari</h2>", "<ul>"]
    for index, iframe in enumerate(iframes, start=1):
        title = html.escape(iframe.get("title") or f"Video {index}")
        src = html.escape(iframe.get("src") or "")
        parts.append(f'<li><a href="{src}">{title}</a></li>')
    parts.extend(["</ul>", "</section>"])
    return "\n".join(parts)


def build_lesson_document(section_title, title, parser, video_files, materials):
    notices = normalize_notice_texts(parser.notices)
    body_parts = [
        '<header class="lesson-header">',
        f'<p class="section-title">{html.escape(section_title)}</p>' if section_title else "",
        f"<h1>{html.escape(title)}</h1>",
        "</header>",
    ]

    if parser.content_html:
        body_parts.append(f'<section class="lesson-content">{parser.content_html}</section>')

    video_html = build_video_section_html(video_files)
    if video_html:
        body_parts.append(video_html)
    elif parser.iframes:
        body_parts.append(build_external_video_links_html(parser.iframes))

    if notices:
        note_items = "".join(f"<li>{html.escape(notice)}</li>" for notice in notices)
        body_parts.append('<section class="lesson-notes"><h2>Notlar</h2><ul>' + note_items + "</ul></section>")

    materials_html = build_materials_section_html(materials)
    if materials_html:
        body_parts.append(materials_html)

    document = f"""<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; line-height: 1.6; margin: 32px auto; max-width: 960px; padding: 0 20px; color: #1f2937; }}
    .section-title {{ color: #6b7280; font-size: 14px; letter-spacing: 0.04em; text-transform: uppercase; margin-bottom: 8px; }}
    h1, h2 {{ color: #111827; }}
    h3 {{ color: #1f2937; margin: 16px 0 8px; }}
    video {{ display: block; width: 100%; max-width: 100%; margin-top: 12px; background: #000; border-radius: 12px; }}
    .lesson-video {{ margin: 0 0 28px; }}
    .lesson-content, .lesson-videos, .lesson-materials, .lesson-notes {{ margin-top: 32px; }}
    .video-transcript pre {{ white-space: pre-wrap; background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px; overflow-wrap: anywhere; }}
    a {{ color: #0f62fe; }}
  </style>
</head>
<body>
{''.join(part for part in body_parts if part)}
</body>
</html>
"""
    return document


def build_lesson_text(section_title, title, parser, video_files, materials):
    lines = []
    if section_title:
        lines.append(section_title)
    lines.append(title)

    if parser.content_html:
        lines.extend(["", html_to_text(parser.content_html)])

    if video_files:
        lines.extend(["", "Videolar:"])
        for video in video_files:
            lines.append(f"- {video.get('title') or video['file']}: {video['file']}")
            transcript_text = (video.get("transcript") or {}).get("text", "").strip()
            if transcript_text:
                lines.extend(["", "Video Transcript:", transcript_text])
    elif parser.iframes:
        lines.extend(["", "Harici Video Kaynaklari:"])
        for iframe in parser.iframes:
            lines.append(f"- {iframe.get('title') or 'Video'}: {iframe.get('src') or ''}")

    notices = normalize_notice_texts(parser.notices)
    if notices:
        lines.extend(["", "Notlar:"])
        for notice in notices:
            lines.append(f"- {notice}")

    material_links = materials.get("links", []) if materials else []
    if material_links:
        lines.extend(["", "Materyaller:"])
        for link in material_links:
            text = link.get("text") or link.get("href") or "Materyal"
            href = link.get("href") or ""
            lines.append(f"- {text}: {href}")

    return "\n".join(lines).strip() + "\n"


def get_lesson_dirs(output_dir, lesson_meta, title):
    section_title = lesson_meta.get("section_title") or "Diger"
    section_dir = os.path.join(
        output_dir,
        ordered_slug(lesson_meta.get("section_index") or 1, section_title, "section"),
    )
    lesson_dir = os.path.join(
        section_dir,
        ordered_slug(lesson_meta.get("lesson_in_section") or 1, title, "lesson"),
    )
    return section_title, section_dir, lesson_dir


def save_lesson(output_dir, lesson_meta, page_url, parser, materials, lp_data, video_files=None):
    title = parser.lesson_title or lesson_meta.get("title") or "lesson"
    section_title, section_dir, lesson_dir = get_lesson_dirs(output_dir, lesson_meta, title)
    ensure_dir(lesson_dir)

    html_path = os.path.join(lesson_dir, "lesson.html")
    txt_path = os.path.join(lesson_dir, "lesson.txt")
    meta_path = os.path.join(lesson_dir, "lesson.json")
    materials_html_path = os.path.join(lesson_dir, "materials.html")

    lesson_html = build_lesson_document(section_title, title, parser, video_files or [], materials)
    lesson_text = build_lesson_text(section_title, title, parser, video_files or [], materials)

    write_text(html_path, lesson_html)
    write_text(txt_path, lesson_text)
    if materials.get("html"):
        write_text(materials_html_path, materials["html"])

    meta = {
        "global_index": lesson_meta.get("global_index"),
        "section_index": lesson_meta.get("section_index"),
        "lesson_in_section": lesson_meta.get("lesson_in_section"),
        "section_title": section_title,
        "title": title,
        "page_url": page_url,
        "prev_url": parser.prev_url,
        "next_url": parser.next_url,
        "lesson_meta": lesson_meta,
        "iframes": parser.iframes,
        "materials": {
            "links": materials.get("links", []),
            "html_file": "materials.html" if materials.get("html") else None,
        },
        "videos": video_files or [],
        "files": {"html": "lesson.html", "text": "lesson.txt", "json": "lesson.json"},
        "directories": {
            "section": safe_relpath(section_dir, output_dir),
            "lesson": safe_relpath(lesson_dir, output_dir),
        },
        "content_type": "+".join(
            [item for item in ["text" if parser.content_html else "", "video" if (video_files or parser.iframes) else ""] if item]
        )
        or "unknown",
        "lp_rest_load_ajax": lp_data.get("lp_rest_load_ajax"),
    }
    write_text(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))
    return meta
