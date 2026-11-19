import argparse
import json
from pathlib import Path
import fitz

p=argparse.ArgumentParser()
p.add_argument('pdf')
p.add_argument('output')
a=p.parse_args()
with fitz.open(a.pdf) as document:
    pages = [page.get_text() for page in document]
text = '\n\n'.join(f'--- PDF page {i+1} ---\n'+page for i, page in enumerate(pages))
readable_pages = sum(bool(page.strip()) for page in pages)
complete = bool(pages) and readable_pages == len(pages)
Path(a.output).write_text(text, encoding='utf-8')
print(json.dumps({'pages': len(pages), 'readablePages': readable_pages,
                  'characters': sum(len(page.strip()) for page in pages),
                  'representation': 'fullText' if complete else 'section' if readable_pages else 'metadata',
                  'limitations': [] if complete else ['Pages without extractable text require OCR or explicit page-level review before a full-text audit']}))
