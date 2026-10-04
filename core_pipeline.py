"""
NameThyPdf - Core Metadata Resolution Engine
Standardized academic PDF renamer and Zotero RIS catalog generator.
Features exact identifier resolution (DOI, ISBN, IA ID) with Groq LLM fallback.
"""

import os
import re
import json
import shutil
import time
import urllib.parse
import platform
import requests
import pymupdf
import pytesseract
from pdf2image import convert_from_path

# ================= PLATFORM CONFIGURATION =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if platform.system() == "Windows":
    POPPLER_PATH = os.path.join(BASE_DIR, "poppler", "Library", "bin")
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
else:
    POPPLER_PATH = None
    for bin_path in ["/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract", "/usr/bin/tesseract"]:
        if os.path.exists(bin_path):
            pytesseract.pytesseract.tesseract_cmd = bin_path
            break

HTTP_HEADERS = {"User-Agent": "NameThyPdf/1.0 (mailto:namethypdf@example.com)"}
REQUEST_TIMEOUT = 12

RIS_TYPE_MAP = {
    "Journal Article": "JOUR",
    "Book": "BOOK",
    "Book Chapter": "CHAP",
    "Report": "RPRT",
    "Working Paper": "RPRT",
    "Thesis": "THES",
    "Conference Paper": "CPAPER",
    "Book Review": "JOUR",
    "Encyclopedia Article": "ENCYC",
    "Web Page": "ELEC",
    "Generic": "GEN"
}

STOP_ENTITIES = {
    "university press", "springer", "elsevier", "routledge", "bloomsbury",
    "hachette", "unknown", "document", "frontmatter", "null", "none", "n/a", "author"
}

# ================= PATH & STRING UTILITIES =================

def win_safe(path: str) -> str:
    """Appends extended path prefix on Windows to prevent MAX_PATH truncation."""
    abs_p = os.path.abspath(path)
    if os.name == 'nt' and not abs_p.startswith('\\\\?\\'):
        return f"\\\\?\\{abs_p}"
    return abs_p

def sanitize_text(text: str) -> str:
    """Normalizes quotes, dashes, and invalid filesystem characters."""
    if not text or not isinstance(text, str): 
        return ""
    replacements = {'’': "'", '‘': "'", '“': '"', '”': '"', '–': '-', '—': '-', '…': ' '}
    for k, v in replacements.items(): 
        text = text.replace(k, v)
    text = re.sub(r'[\\/*?:"<>|„“”=\n\r\t]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def clean_part(text: str, max_chars: int = 65) -> str:
    """Cleans and capitalizes bibliographic strings with length guardrails."""
    if not text: 
        return ""
    t = sanitize_text(text)
    t = re.sub(r'-{2,}\s*page\s*\d+\s*-{2,}', '', t, flags=re.I)
    words = [w if (re.search(r'[a-z][A-Z]', w) or w.isupper()) else w.capitalize() for w in t.split()]
    formatted = " ".join(words)
    if len(formatted) <= max_chars: 
        return formatted
    return formatted[:max_chars].rsplit(" ", 1)[0].strip()

def is_valid_isbn(s: str) -> bool:
    """Validates ISBN-10 and ISBN-13 checksums."""
    clean = re.sub(r'[^0-9X]', '', s.upper())
    if len(clean) == 10:
        val = sum((10 - i) * (10 if c == 'X' else int(c)) for i, c in enumerate(clean))
        return val % 11 == 0
    elif len(clean) == 13:
        check = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(clean[:12]))
        return (10 - (check % 10)) % 10 == int(clean[12])
    return False

# ================= TEXT EXTRACTION =================

def scan_pdf_text(pdf_path: str) -> str:
    """Extracts text from the first pages, falls back to OCR if unreadable."""
    safe_path = win_safe(pdf_path)
    text_content = []
    try:
        doc = pymupdf.open(safe_path)
        for i in range(min(5, len(doc))):
            text_content.append(doc[i].get_text().strip())
        full_text = "\n".join(text_content)
        
        if len(full_text.strip()) < 50:
            images = convert_from_path(safe_path, first_page=1, last_page=min(4, len(doc)), poppler_path=POPPLER_PATH)
            full_text = "\n".join([pytesseract.image_to_string(img) for img in images])
            
        doc.close()
        return full_text[:5000]
    except Exception:
        return ""

# ================= IDENTIFIER RESOLUTION =================

def extract_all_identifiers(filename: str, text: str) -> dict:
    """Extracts DOI, ISBN, and Internet Archive IDs using regular expressions."""
    ids = {"doi": "", "isbn": "", "ia_id": ""}
    combined = f"{filename}\n{text}"
    
    # Extract DOI
    doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', combined)
    if doi_match:
        ids["doi"] = doi_match.group(0).rstrip('.)/,_')
    else:
        doi_fn = re.search(r'10\.\d{4,9}[_][\w\-.]+', filename)
        if doi_fn:
            ids["doi"] = doi_fn.group(0).replace('_', '/', 1)

    # Extract ISBN
    isbns = re.findall(r'(?:ISBN(?:-1[03])?:?\s*)?([0-9Xx\-\s]{10,25})', combined, re.I)
    for cand in isbns:
        raw = re.sub(r'[^0-9X]', '', cand.upper())
        if is_valid_isbn(raw):
            ids["isbn"] = raw
            break

    # Extract Internet Archive ID
    ia_match = re.search(r'(?:archive\.org\/details\/|urn:lcp:)([a-zA-Z0-9_\-\.]+)', combined)
    if ia_match:
        ids["ia_id"] = ia_match.group(1).rstrip('._/')
        
    return ids

def resolve_crossref_doi(doi: str) -> dict:
    """Queries Crossref API for verified DOI metadata."""
    if not doi: 
        return {}
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            m = r.json().get("message", {})
            api_title = m.get("title", [""])[0]
            if not api_title: 
                return {}
            
            authors = [{"last": a.get("family", "").strip(), "first": a.get("given", "").strip()} 
                       for a in m.get("author", []) if a.get("family")]
            
            c_type = m.get("type", "")
            doc_type = "Journal Article"
            if "book" in c_type: doc_type = "Book"
            if c_type == "book-chapter": doc_type = "Book Chapter"
            if "review" in c_type: doc_type = "Book Review"
            if "proceedings" in c_type or "conference" in c_type: doc_type = "Conference Paper"
            if "report" in c_type: doc_type = "Report"

            year = ""
            date_parts = m.get("published-print", {}).get("date-parts", [[]])[0]
            if not date_parts: 
                date_parts = m.get("published-online", {}).get("date-parts", [[]])[0]
            if date_parts: 
                year = str(date_parts[0])

            return {
                "source": "Crossref", "main_title": api_title,
                "subtitle": m.get("subtitle", [""])[0] if m.get("subtitle") else "",
                "authors": authors, "editors": [],
                "book_title": m.get("container-title", [""])[0] if m.get("container-title") else "",
                "journal_name": m.get("container-title", [""])[0] if m.get("container-title") else "",
                "publisher": m.get("publisher", ""), "year": year,
                "doi": m.get("DOI", ""), "pages": m.get("page", ""),
                "issn": m.get("ISSN", [""])[0] if m.get("ISSN") else "",
                "doc_type": doc_type
            }
    except Exception:
        pass
    return {}

def resolve_google_books(isbn: str) -> dict:
    """Queries Google Books API for verified ISBN metadata."""
    if not isbn: 
        return {}
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{urllib.parse.quote(isbn)}"
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            if "items" in data and len(data["items"]) > 0:
                vol = data["items"][0].get("volumeInfo", {})
                api_title = vol.get("title", "")
                if api_title:
                    authors = []
                    for author_name in vol.get("authors", []):
                        parts = author_name.split()
                        if len(parts) >= 2: 
                            authors.append({"first": " ".join(parts[:-1]).title(), "last": parts[-1].title()})
                        elif len(parts) == 1: 
                            authors.append({"first": parts[0].title(), "last": ""})
                            
                    pub_date = vol.get("publishedDate", "")
                    return {
                        "source": "Google Books", "main_title": api_title,
                        "subtitle": vol.get("subtitle", ""), "authors": authors,
                        "year": pub_date[:4] if pub_date else "",
                        "publisher": vol.get("publisher", ""), "doc_type": "Book"
                    }
    except Exception:
        pass
    return {}

def resolve_openlibrary_isbn(isbn: str) -> dict:
    """Queries OpenLibrary API as fallback for ISBN metadata."""
    if not isbn: 
        return {}
    url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            key = f"ISBN:{isbn}"
            if key in data:
                vol = data[key]
                api_title = vol.get("title", "")
                if api_title:
                    authors = []
                    for author in vol.get("authors", []):
                        parts = author.get("name", "").split()
                        if len(parts) >= 2: 
                            authors.append({"first": " ".join(parts[:-1]).title(), "last": parts[-1].title()})
                        elif len(parts) == 1: 
                            authors.append({"first": parts[0].title(), "last": ""})
                            
                    pub_date = vol.get("publish_date", "")
                    year = re.search(r'\b(19|20)\d{2}\b', pub_date)
                    publishers = vol.get("publishers", [])
                    return {
                        "source": "OpenLibrary", "main_title": api_title,
                        "subtitle": vol.get("subtitle", ""), "authors": authors,
                        "year": year.group(0) if year else "",
                        "publisher": publishers[0].get("name", "") if publishers else "",
                        "doc_type": "Book"
                    }
    except Exception:
        pass
    return {}

def resolve_internet_archive(ia_id: str) -> dict:
    """Queries Internet Archive Metadata API for verified archive items."""
    if not ia_id: 
        return {}
    url = f"https://archive.org/metadata/{urllib.parse.quote(ia_id)}"
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            meta = r.json().get("metadata", {})
            title = meta.get("title", "")
            if not title: 
                return {}
            
            creator = meta.get("creator", "")
            authors = []
            if isinstance(creator, str) and creator:
                parts = creator.replace(',', ' ').split()
                if len(parts) >= 2:
                    authors.append({"first": " ".join(parts[:-1]).title(), "last": parts[-1].title()})
                elif len(parts) == 1:
                    authors.append({"first": parts[0].title(), "last": ""})
            elif isinstance(creator, list):
                for c in creator:
                    p = str(c).replace(',', ' ').split()
                    if len(p) >= 2: 
                        authors.append({"first": " ".join(p[:-1]).title(), "last": p[-1].title()})
                    elif len(p) == 1: 
                        authors.append({"first": p[0].title(), "last": ""})

            date_val = str(meta.get("date") or meta.get("year") or "")
            year_match = re.search(r'\b(19|20)\d{2}\b', date_val)
            
            return {
                "source": "Internet Archive", "main_title": title,
                "subtitle": "", "authors": authors,
                "year": year_match.group(0) if year_match else "",
                "publisher": meta.get("publisher", ""), "doc_type": "Book"
            }
    except Exception:
        pass
    return {}

# ================= GROQ API RESOLUTION =================

def resolve_metadata_groq(filename: str, front_text: str, api_key: str = None) -> dict:
    """Fallback LLM metadata extractor using Groq with exponential backoff on 429."""
    key = api_key or os.getenv("GROQ_API_KEY")
    if not key:
        print("    [!] Groq Warning: No API key found.")
        return {}

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }

    clean_sample = front_text.replace('"', "'").replace('\\', ' ')
    prompt = f"""
Analyze the filename and front text of an academic document to extract metadata.

ORIGINAL FILENAME: {filename}

GUIDELINES:
1. The original filename is your best hint for true human authors and title.
2. Choose DOC_TYPE strictly from: "Book", "Journal Article", "Book Chapter", "Conference Paper", "Working Paper", "Report", "Thesis".

Return ONLY valid JSON matching this schema:
{{
  "main_title": "",
  "subtitle": "",
  "book_title": "",
  "journal_name": "",
  "authors": [{{"first": "", "last": ""}}],
  "editors": [{{"first": "", "last": ""}}],
  "year": "",
  "publisher": "",
  "doc_type": ""
}}

TEXT:
{clean_sample[:2000]}
"""

    payload = {
        "model": "openai/gpt-oss-20b",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.0
    }

    # Retry up to 3 times if rate-limited
    for attempt in range(3):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"]["content"]
                data = json.loads(content)
                data["source"] = "Groq (GPT-OSS-20b)"
                if str(data.get("journal_name", "")).strip() and data.get("doc_type") not in ["Journal Article", "Book Review"]:
                    data["doc_type"] = "Journal Article"
                return data
            elif r.status_code == 429:
                wait_time = (attempt + 1) * 3
                print(f"    [!] Rate limited on '{filename[:35]}...'. Waiting {wait_time}s before retry (Attempt {attempt+1}/3)...")
                time.sleep(wait_time)
            else:
                print(f"    [!] Groq API Error {r.status_code}: {r.text[:100]}")
                break
        except Exception as e:
            print(f"    [!] Groq Request Exception: {e}")
            break

    return {}
# ================= PIPELINE EXECUTION =================

def process_single_pdf(filepath: str, library_dir: str, quarantine_dir: str, central_ris_path: str, groq_key: str = None):
    """Processes an individual PDF through resolution, renaming, and RIS export."""
    filename = os.path.basename(filepath)
    front_text = scan_pdf_text(filepath)
    if not front_text:
        shutil.copy2(win_safe(filepath), win_safe(os.path.join(quarantine_dir, filename)))
        return False, filename, "Unreadable text layer"

    meta = {}
    ids = extract_all_identifiers(filename, front_text)

    # 1. Exact Database Lookups
    if ids["doi"]:
        meta = resolve_crossref_doi(ids["doi"])
    if not meta and ids["isbn"]:
        meta = resolve_google_books(ids["isbn"]) or resolve_openlibrary_isbn(ids["isbn"])
    if not meta and ids["ia_id"]:
        meta = resolve_internet_archive(ids["ia_id"])

    # 2. Groq LLM Fallback
    if not meta:
        cand = resolve_metadata_groq(filename, front_text, groq_key)
        if cand and cand.get("main_title"):
            meta = cand

    raw_main_title = str(meta.get("main_title", "")).strip()
    if not meta or not raw_main_title or raw_main_title.lower() in [
        "introduction", "preface", "contents", "table of contents", 
        "chapter", "index", "conclusion", "null", "none", "n/a", "copyright"
    ]:
        shutil.copy2(win_safe(filepath), win_safe(os.path.join(quarantine_dir, filename)))
        return False, filename, "Failed to resolve metadata"

    # Title cleanup
    raw_main_title = re.sub(r'(?i)copyright.*', '', raw_main_title)
    raw_main_title = re.sub(r'(?i)all rights reserved.*', '', raw_main_title)
    raw_main_title = re.sub(r'^(19|20)\d{2}[-\s]+', '', raw_main_title)
    clean_main = clean_part(raw_main_title, max_chars=80).title()
    if len(clean_main) < 2 and len(raw_main_title) > 0:
        clean_main = raw_main_title.replace(" ", ".")

    # Surnames extraction and filtering
    def extract_surnames(person_list):
        extracted = []
        for p in (person_list or []):
            if isinstance(p, dict):
                l_name = p.get("last", "").strip()
                f_name = p.get("first", "").strip()
                
                if l_name: 
                    l = sanitize_text(l_name).title()
                elif f_name: 
                    l = sanitize_text(f_name.split()[-1]).title()
                else: 
                    continue
                    
                if l and len(l) < 30 and l.lower() not in STOP_ENTITIES:
                    if not re.search(r'(?i)(copyright|rights reserved|published|printed|ltd|inc|ventures|press|group|company|llc|corp|muse|text)', l):
                        extracted.append(l)
        return extracted

    surnames = extract_surnames(meta.get("authors")) or extract_surnames(meta.get("editors"))

    if not surnames:
        authors_prefix = "UnknownAuthor"
    elif len(surnames) > 3:
        authors_prefix = f"{surnames[0]}.et.al"
    else:
        authors_prefix = ".".join(surnames)

    title_suffix = clean_main.replace(" ", ".")
    target_basename = re.sub(r'\.+', '.', f"{authors_prefix}_{title_suffix}").strip('_.')

    final_pdf_path = os.path.join(library_dir, f"{target_basename}.pdf")
    counter = 1
    while os.path.exists(win_safe(final_pdf_path)):
        final_pdf_path = os.path.join(library_dir, f"{target_basename}_{counter}.pdf")
        counter += 1

    try:
        write_ris_record(central_ris_path, meta, final_pdf_path)
        embed_pdf_metadata(filepath, final_pdf_path, meta, surnames)
        return True, os.path.basename(final_pdf_path), meta.get("doc_type", "Generic")
    except Exception as e:
        shutil.copy2(win_safe(filepath), win_safe(os.path.join(quarantine_dir, filename)))
        return False, filename, str(e)

def run_pipeline(input_dir: str, output_dir: str, groq_key: str = None):
    """Executes the standard pipeline across all input PDF documents with rate pacing."""
    library_dir = os.path.join(output_dir, "Library")
    quarantine_dir = os.path.join(output_dir, "_Quarantine")
    os.makedirs(win_safe(library_dir), exist_ok=True)
    os.makedirs(win_safe(quarantine_dir), exist_ok=True)
    central_ris_path = os.path.join(output_dir, "collection.ris")

    pdf_files = [f for f in os.listdir(input_dir) if f.lower().endswith(".pdf")]
    results = []
    for f in pdf_files:
        path = os.path.join(input_dir, f)
        res = process_single_pdf(path, library_dir, quarantine_dir, central_ris_path, groq_key)
        results.append(res)
        # Delay between requests to respect free-tier Groq TPM/RPM limits
        time.sleep(2.0)
        
    return results

def write_ris_record(ris_filepath: str, meta: dict, target_pdf_path: str):
    """Appends bibliographic metadata record to centralized RIS file."""
    doc_type = meta.get("doc_type", "Generic")
    ris_type = RIS_TYPE_MAP.get(doc_type, "GEN")

    full_title = str(meta.get("main_title") or "").strip().title()
    subtitle = str(meta.get("subtitle") or "").strip()
    if subtitle and subtitle.lower() not in ["null", "none", ""]: 
        full_title += f": {subtitle.title()}"

    lines = [f"TY  - {ris_type}", f"TI  - {full_title}"]

    for a in (meta.get("authors") or []):
        if isinstance(a, dict):
            l = str(a.get("last") or "").strip().title()
            f = str(a.get("first") or "").strip().title()
            if not l and f and len(f.split()) > 1:
                parts = f.split()
                f, l = " ".join(parts[:-1]), parts[-1]
            if l or f: 
                lines.append(f"AU  - {l}, {f}".strip(" ,"))

    if ris_type == "CHAP" and meta.get("book_title"): 
        lines.append(f"T2  - {str(meta.get('book_title')).title()}")
    if ris_type == "JOUR" and meta.get("journal_name"): 
        lines.append(f"JO  - {str(meta.get('journal_name')).title()}")
        
    match_year = re.search(r'\b(19|20)\d{2}\b', str(meta.get("year") or ""))
    if match_year: 
        lines.append(f"PY  - {match_year.group(0)}")

    for key, ris_code in [("publisher", "PB"), ("city", "CY"), ("volume", "VL"), ("issue", "IS"), ("pages", "SP"), ("doi", "DO"), ("issn", "SN")]:
        val = str(meta.get(key) or "").strip()
        if val and val.lower() not in ["null", "none", ""]:
            lines.append(f"{ris_code}  - {val.title() if key in ['publisher', 'city'] else val}")

    lines.append(f"L1  - {os.path.abspath(target_pdf_path)}")
    lines.append("ER  - \n")

    with open(win_safe(ris_filepath), "a", encoding="utf-8") as f: 
        f.write("\n".join(lines) + "\n")

def embed_pdf_metadata(source_pdf: str, dest_pdf: str, meta: dict, surnames: list):
    """Embeds Title, Author, and Subject into PDF XMP/DocInfo tags."""
    safe_dest = win_safe(dest_pdf)
    shutil.copy2(win_safe(source_pdf), safe_dest)
    try:
        doc = pymupdf.open(safe_dest)
        doc.set_metadata({
            "title": str(meta.get("main_title") or "").strip().title(),
            "author": "; ".join(surnames),
            "subject": str(meta.get("doc_type") or "Academic Document"),
            "producer": "NameThyPdf Engine"
        })
        doc.save(safe_dest, incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
        doc.close()
    except Exception:
        pass