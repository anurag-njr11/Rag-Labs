# Documents

The Documents tab is where source material enters a project and where you check that it was read correctly.

## Adding documents

**Upload files.** Drag files onto the drop zone or click to browse. Supported formats are `.pdf`, `.docx`, `.md`, `.markdown`, `.mdx`, `.txt`, `.rst`, `.html` and `.htm`, up to 100 MB each. Uploading the same content twice is detected and skipped.

**Add from URL.** Paste a link to fetch a page. Turn on **Crawl sitemap** to follow a site's sitemap and fetch several pages (the crawl is depth-limited).

Every document is parsed, chunked and indexed with the active version's settings. The original file is kept, so changing the pipeline later re-parses from the source and not from a lossy copy.

## Parse quality

After upload each document shows a **parse quality** indicator: good, fair or poor. The card lists how many characters were extracted, how many tables were found, whether OCR was used and how many pages came out empty. Check this before blaming retrieval: a scanned PDF with no text layer produces nothing to retrieve, and no retrieval setting can fix that.

Tables are kept as Markdown tables and treated as atomic chunks, so a row is not separated from its header.

## Viewing chunks

Open a document to see the exact chunks it was split into with the current settings, with their headings, page numbers and token counts. This is the fastest way to judge whether the chunk size and strategy suit your content.

## Metadata

Each file's last-modified date is kept (from your computer, or the page's `Last-Modified` header for URLs) and shown in the **Modified** column. Markdown files can carry front matter:

```markdown
---
status: published
stale_after: 2027-01-31
verified: true
sources: [https://example.com/spec]
---
```

| Field | Meaning |
| --- | --- |
| `status` | For example draft, published or deprecated |
| `stale_after` | A date after which the document should be reviewed |
| `verified` | `true`, or the date it was last verified by a person |
| `sources` | Where the content came from |

Edit these for any document with the tag icon on its row. Saving metadata never rebuilds the index. The dialog also shows the **usage count**: how often the document's passages appeared in Playground and API answers.

Metadata matters in two places. [Corpus Health](/docs/health) uses it to flag stale and deprecated documents, and the retrieve option `okf_policy` can leave out expired documents and prefer better-verified ones (see the [pipeline reference](/docs/pipeline-reference)).

## Import and export OKF bundles

The Open Knowledge Format is a `.zip` of Markdown files with YAML front matter. **Import** reads one document per file (the path inside the bundle is kept in the name), takes the metadata from the front matter, and skips files it cannot use with a reason. **Export** writes the corpus back as a bundle with provenance, trust tier (human, process or agent, from `verified`), lifecycle, usage counts and the latest Corpus Health findings, plus an index.

## Reindexing and removing

- **Reindex** a single document after fixing it.
- **Delete** removes a document from every index. This cannot be undone.
- If the active version's index is out of date after changes, the project header offers **Build index**, and the Playground and API update it automatically on the next question.

> **Tip** Eval questions whose source document you delete will always miss. After large document changes, regenerate the eval set (see [Evaluate](/docs/evaluate)).
