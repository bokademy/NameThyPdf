
# 📖 NameThyPdf

> **"Pdf namer for academics by an academic who has little to no knowledge of programming."**
>
> *This program was mostly written via AI, therefore it would only be reasonable if I allowed AI to write the ReadMe section. The following part is also mostly by Gemini :)
> \
> Bring sanity to thy messy academic PDFs. Automated identifier resolution, intelligent LLM extraction, and Zotero export.*

## 📌 Motivation

As scholars, our download folders and desktop directories often turn into chaotic graveyards of randomly hashed filenames:

* `1-s2.0-S0160791X2200021X-main.pdf`

* `somebookname -- Deborah Cowen... -- Anna’s Archive.pdf`

* `978-3-030-12345-6.pdf`

Existing bibliographic managers struggle when raw PDF metadata is absent or corrupted. **NameThyPdf** is a lightweight, zero-install web application designed specifically for researchers. It parses your PDF files, resolves their true scholarly identities via verified academic APIs, falls back gracefully to cloud LLM extraction, and packages everything into clean `Author_Title.pdf` files with an auto-generated, Zotero-ready `.ris` catalog.

## ⚙️ Architecture & Pipeline

```
[ Messy Input PDF ]
         │
         ▼
[ Text / OCR Extraction (PyMuPDF + Tesseract Fallback) ]
         │
         ├───► 1. Exact Identifier Search (DOI / ISBN / IA ID)
         │           │
         │           ├── Found DOI  ──► Crossref API
         │           ├── Found ISBN ──► Google Books / OpenLibrary API
         │           └── Found IA   ──► Internet Archive Metadata API
         │
         └───► 2. LLM Inference Fallback (Groq API: openai/gpt-oss-20b)
                     │
                     ▼
         [ Metadata Resolution Engine ]
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
[ Clean Renamed PDF ]    [ Zotero RIS Record ]
(Author.et.al_Title.pdf)   (collection.ris)
         │                       │
         └───────────┬───────────┘
                     ▼
       [ Downloadable ZIP Library ]

```

## ✨ Features

* **Exact Identifier Lookups:** Queries official metadata registries (Crossref, Google Books, OpenLibrary, Internet Archive) before touching LLMs.

* **Intelligent LLM Parsing:** Utilizes lightweight, fast Groq API endpoints (`openai/gpt-oss-20b`) with exponential backoff to handle rate limits and complex filenames.

* **Resilient File Naming:** Automatically normalizes smart quotes, long paths (`MAX_PATH` on Windows), and forbidden filesystem characters into uniform `Author_Title.pdf` naming conventions.

* **Embedded PDF Metadata:** Writes resolved title, authors, and document types straight into the PDF XMP/DocInfo tags.

* **Direct Zotero / EndNote Ingestion:** Automatically compiles an index (`collection.ris`) linking each entry directly to its curated PDF.

* **Quarantine Safeguard:** Unreadable or unresolved files are safely isolated in a `_Quarantine` folder without altering your originals.

## 🚀 Quick Start (Web App)

You do **not** need to install Python or understand code to use NameThyPdf:

1. Visit the live tool: [**namethypdf.streamlit.app**](https://namethypdf.streamlit.app)
2. Drag and drop your messy PDF files into the upload box.

3. Click **"Start Renaming & Organizing"**.

4. Download the resulting `NameThyPdf_Curated_Library.zip`.

5. Open Zotero, go to **File** $\rightarrow$ **Import**, and select `collection.ris` to ingest all items with metadata and attached files.

## 💻 Local Installation (For Developers & Self-Hosters)

If you wish to run the app locally on your own machine:

### 1. Clone the Repository

```
git clone https://github.com/YOUR_USERNAME/NameThyPdf.git
cd NameThyPdf

```

### 2. Configure Environment & Dependencies

```
python -m venv venv
# On Windows:
venv\Scripts\activate
# On macOS / Linux:
source venv/bin/activate

pip install -r requirements.txt

```

### 3. Set Up API Credentials

Create a `.streamlit/secrets.toml` file in the project root:

```
GROQ_API_KEY = "gsk_your_groq_api_key_here"

```

### 4. Run the Streamlit Application

```
streamlit run app.py

```

Open your browser at `http://localhost:8501`.

## ⚖️ Scholarly Disclaimer

> **Notice:** Automated metadata resolution is an aid, not a miracle. While NameThyPdf strives for high precision through verified registry lookups, algorithmic extraction can occasionally misidentify frontmatter or non-standard preprints. Always inspect thy generated references before final citation.

## 📄 License

This project is free software licensed under the **GNU General Public License v3.0 (GPL-3.0)**.

You are free to run, study, share, and modify this work, provided all derivative software remains open-source under identical terms.

See the [LICENSE](LICENSE) file for complete details.

## ✍️ Citation & Attribution

If you use NameThyPdf in academic workflows or find it helpful in organizing research repositories, consider acknowledging it:

```
@software{Kaynar_NameThyPdf_2026,
  author       = {Burak Kaynar},
  title        = {{NameThyPdf: Automated Academic PDF Organizer \& Metadata Resolver}},
  year         = {2026},
  url          = {https://github.com/YOUR_USERNAME/NameThyPdf}
}

```
