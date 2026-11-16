from pathlib import Path
from io import BytesIO
import hashlib
import json
import re
import pandas as pd
import streamlit as st
from google import genai
import fitz
import shutil
from datetime import datetime

st.set_page_config(page_title='ASTRA-FIRE AI', page_icon='🔥', layout='wide')
ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / 'data.csv'
CATEGORIES = ['Spacecraft Fire Safety', 'Droplets', 'Gaseous - Premixed and Non-Premixed', 'High Pressure / Supercritical', 'Solid Fuels']
FIELDS = ['gravity', 'summary', 'insight', 'source', 'doi', 'airflow_max_cm_s', 'oxygen_note']

@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=st.secrets['GEMINI_API_KEY'], http_options={'timeout': 60000, 'retry_options': {'attempts': 1}})

def read_db():
    if not DATA_PATH.exists():
        st.error('data.csv not found next to app.py')
        st.stop()
    data = pd.read_csv(DATA_PATH, dtype=str).fillna('')
    for col in ['id','name','topic','category','summary','insight','source','doi','evidence_type','gravity','airflow_max_cm_s','oxygen_note','flame_spread_rate_mm_s']:
        if col not in data: data[col] = ''
    return data

def extract_pdf(upload):
    doc = fitz.open(stream=upload.getvalue(), filetype='pdf')
    try:
        pages = [page.get_text('text') for page in doc]
    finally:
        doc.close()
    return pages

def numbered(pages, limit=55000):
    return '\n\n'.join(f'[PAGE {i+1}]\n{txt}' for i,txt in enumerate(pages))[:limit]

def ask_gemini(prompt):
    response = get_gemini_client().models.generate_content(model='gemini-3.5-flash-lite', contents=prompt, config={'system_instruction': 'You are ASTRA-FIRE AI, a scientific research assistant. Use only the supplied evidence when analyzing documents. Do not invent measurements, citations, risk scores, or experimental results. Distinguish observed findings, possible mechanisms, and unknowns. Never claim operational safety certification.'})
    return response.text or 'No response generated.'

def clean_json(text):
    match = re.search(r'\{.*\}', text, re.S)
    if not match: raise ValueError('Gemini did not return a JSON object.')
    return json.loads(match.group(0))

def classify(pages):
    prompt = f'''Classify this scientific document. Return ONLY a valid JSON object with keys: title (string), categories (array of exact category names), topic (short string), gravity (string), airflow_max_cm_s (string, only if explicitly measured), oxygen_note (string), summary (string), insight (string), evidence_type (string), doi (string), flame_spread_rate_mm_s (string, only if explicitly measured), explanation (string with page references), missing_information (string). Categories must be selected from {json.dumps(CATEGORIES)}. Multiple categories are allowed. Never invent quantitative values. Use empty strings for unknown fields. No risk score. Document:\n{numbered(pages)}'''
    obj = clean_json(ask_gemini(prompt))
    obj['categories'] = [c for c in obj.get('categories', []) if c in CATEGORIES]
    return obj

st.title('🚀 ASTRA-FIRE AI')
st.caption('Evidence-first fire safety research explorer | NASA Space Apps prototype')
st.warning('Research prototype. Not a validated fire-risk predictor or operational safety tool.')
df = read_db()
page = st.sidebar.radio('Explore', ['Overview','Research Explorer','Evidence Ranking','AI Insights','Admin - Research Upload'])

if page == 'Overview':
    a,b,c = st.columns(3)
    a.metric('Investigations', len(df))
    b.metric('NASA PSI records', int(df.id.str.startswith('PSI-').sum()))
    c.metric('Measured flame spread rates', int(pd.to_numeric(df.flame_spread_rate_mm_s, errors='coerce').notna().sum()))
    st.subheader('Research Coverage')
    counts = {category: 0 for category in CATEGORIES}
    unclassified = 0
    for value in df.category:
        assigned = set(x.strip() for x in str(value).split(';'))
        matches = assigned.intersection(CATEGORIES)
        if not matches: unclassified += 1
        for cat in matches: counts[cat] += 1
    chart = pd.DataFrame({'Category': list(counts), 'Documents': list(counts.values())})
    st.bar_chart(chart.set_index('Category'), horizontal=True)
    st.caption(f'{unclassified} unclassified document(s). Multi-category documents count in each applicable category.')
    st.info('The database contains study-level metadata; findings are not necessarily directly comparable.')

elif page == 'Research Explorer':
    topics = st.multiselect('Filter topics', sorted(df.topic.unique()), default=sorted(df.topic.unique()))
    q = st.text_input('Search investigations (keywords)')
    shown = df[df.topic.isin(topics)]
    if q:
        shown = shown[shown.astype(str).apply(lambda col: col.str.contains(q,case=False,regex=False)).any(axis=1)]
    st.dataframe(shown[['id','name','topic','category','gravity','airflow_max_cm_s','oxygen_note','evidence_type','source']], hide_index=True, use_container_width=True)
    for _,r in shown.iterrows():
        with st.expander(f'{r["name"]}: scientific context'):
            st.write(r['summary'])
            st.write('**Interpretation:**',r['insight'])
            if str(r['source']).startswith(('https://','http://')):
                st.markdown(f'[Original source]({r["source"]})')

elif page == 'Evidence Ranking':
    st.subheader('Evidence completeness ranking — not a danger ranking')
    st.write('Completeness counts populated metadata fields. It is NOT a flammability, danger, or safety score.')
    ranked = df.copy()
    ranked['completeness'] = ranked[FIELDS].apply(lambda row: sum(str(v).strip() not in ('','Not extracted') for v in row), axis=1)
    ranked = ranked.sort_values(['completeness','name'], ascending=[False,True])
    st.dataframe(ranked[['name','topic','completeness','evidence_type']], hide_index=True, use_container_width=True)
    st.subheader('Evidence completeness distribution')
    distribution = ranked['completeness'].value_counts().reindex(range(len(FIELDS)+1),fill_value=0)
    st.bar_chart(pd.DataFrame({'Metadata fields present':distribution.index, 'Investigations':distribution.values}).set_index('Metadata fields present'))
    st.caption('A distribution of actual scores is shown. A Gaussian bell curve is not imposed on the data. Higher completeness means better documentation, not greater safety.')

elif page == 'AI Insights':
    st.header('🤖 ASTRA-FIRE AI Assistant')
    st.write('Ask a question or attach research PDFs for evidence-grounded analysis.')
    uploads = st.file_uploader('Attach scientific PDF files',type=['pdf'],accept_multiple_files=True,key='ai_upload')
    question = st.text_area('Your scientific question',placeholder='Identify reported damage mechanisms, fire-spread patterns, uncertainty and potential mitigations.')
    if st.button('Analyze with Gemini'):
        if not question.strip() and not uploads:
            st.warning('Enter a question or attach a PDF.')
        else:
            contexts = []
            for upload in uploads or []:
                try:
                    pages = extract_pdf(upload)
                    if any(x.strip() for x in pages):
                        contexts.append(f'FILE: {upload.name}\n{numbered(pages, 25000)}')
                    else:
                        st.warning(f'{upload.name}: no selectable text (OCR may be needed).')
                except Exception as e:
                    st.error(f'Could not read {upload.name}: {e}')
            prompt = f'''Question: {question or 'Analyze the attached studies.'}\n\nDocuments:\n{chr(10).join(contexts)[:55000]}\n\nRespond with: (1) supported findings and page references where available, (2) patterns related to ignition, flame spread or potential damage, (3) practical research-oriented mitigation hypotheses, (4) uncertainty and missing data, (5) danger ranking: only if a scientifically validated metric and necessary inputs are supplied; otherwise state "Danger ranking cannot be calculated from the available evidence". Never confuse metadata completeness with danger. If no document was attached, state that the answer is general and is not grounded in the local database.'''
            try:
                with st.spinner('Analyzing evidence...'):
                    result = ask_gemini(prompt)
                st.markdown(result)
            except Exception as e:
                st.error(f'Gemini API connection error: {e}')

elif page == 'Admin - Research Upload':
    st.header('📄 Research Upload & Classification')
    st.write('Upload PDF, Excel or CSV research files. Review the records before adding them to data.csv.')
    upload = st.file_uploader('Upload research file', type=['pdf', 'csv', 'xlsx', 'xls'], key='admin_research_file')
    if upload:
        suffix = Path(upload.name).suffix.lower()
        fingerprint = hashlib.sha256(upload.getvalue()).hexdigest()
        if st.session_state.get('upload_fingerprint') != fingerprint:
            st.session_state['upload_fingerprint'] = fingerprint
            st.session_state.pop('classified_record', None)
        if suffix in ('.csv', '.xlsx', '.xls'):
            try:
                if suffix == '.csv':
                    try:
                        incoming = pd.read_csv(BytesIO(upload.getvalue()), dtype=str, encoding='utf-8-sig').fillna('')
                    except UnicodeDecodeError:
                        incoming = pd.read_csv(BytesIO(upload.getvalue()), dtype=str, encoding='cp1252').fillna('')
                else:
                    engine = 'openpyxl' if suffix == '.xlsx' else 'xlrd'
                    workbook = pd.ExcelFile(BytesIO(upload.getvalue()), engine=engine)
                    sheet = st.selectbox('Excel sheet', workbook.sheet_names)
                    incoming = pd.read_excel(workbook, sheet_name=sheet, dtype=str).fillna('')
                incoming.columns = [str(c).strip().lstrip('\ufeff') for c in incoming.columns]
                incoming = incoming.loc[:, ~incoming.columns.duplicated()]
                incoming = incoming.dropna(how='all')
                incoming = incoming.loc[~incoming.astype(str).apply(lambda col: col.str.strip()).eq('').all(axis=1)].copy()
                st.write(f'Found {len(incoming)} row(s) and {len(incoming.columns)} column(s).')
                st.dataframe(incoming.head(30), use_container_width=True, hide_index=True)
                required = ['id', 'name']
                missing = [c for c in required if c not in incoming.columns]
                if missing:
                    st.error('Missing required columns: ' + ', '.join(missing) + '. Use the template below.')
                else:
                    st.subheader('Review imported research')
                    extra = [c for c in incoming.columns if c not in df.columns]
                    if extra:
                        st.warning('Columns not in the current database will not be imported: ' + ', '.join(extra))
                    for c in df.columns:
                        if c not in incoming.columns:
                            incoming[c] = ''
                    incoming = incoming[df.columns].copy()
                    incoming['id'] = incoming['id'].astype(str).str.strip()
                    incoming['name'] = incoming['name'].astype(str).str.strip()
                    existing_ids = set(df['id'].astype(str).str.strip())
                    duplicate_existing = incoming['id'].isin(existing_ids)
                    duplicate_upload = incoming['id'].duplicated(keep=False)
                    missing_identity = incoming['id'].eq('') | incoming['name'].eq('')
                    invalid_categories = incoming['category'].astype(str).apply(
                        lambda v: any(x.strip() not in CATEGORIES for x in v.split(';') if x.strip())
                    )
                    status = pd.Series('Ready', index=incoming.index)
                    status.loc[invalid_categories] = 'Review category'
                    status.loc[missing_identity] = 'Missing ID or title'
                    status.loc[duplicate_upload] = 'Duplicate ID in upload'
                    status.loc[duplicate_existing] = 'ID already exists'
                    preview = incoming[['id', 'name', 'category']].copy()
                    preview.insert(0, 'Import status', status)
                    st.dataframe(preview, use_container_width=True, hide_index=True)
                    valid = status.eq('Ready')
                    st.info(f'{int(valid.sum())} ready to import; {int((~valid).sum())} skipped. Blank categories are allowed but will appear as unclassified.')
                    st.caption('Categories must match the five ASTRA-FIRE labels exactly. Multiple categories use semicolons (;).')
                    if st.button('Import valid records to data.csv', disabled=not valid.any()):
                        try:
                            # Re-read to avoid overwriting records added since the page was loaded.
                            latest = read_db()
                            latest_ids = set(latest['id'].astype(str).str.strip())
                            to_add = incoming.loc[valid & ~incoming['id'].isin(latest_ids)].copy()
                            if to_add.empty:
                                st.warning('No new records to import. The IDs already exist.')
                            else:
                                backup = DATA_PATH.with_name('data_backup_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.csv')
                                shutil.copy2(DATA_PATH, backup)
                                combined = pd.concat([latest, to_add.reindex(columns=latest.columns, fill_value='')], ignore_index=True)
                                combined.to_csv(DATA_PATH, index=False, encoding='utf-8-sig')
                                st.success(f'Imported {len(to_add)} research record(s). Backup saved as {backup.name}. Refresh Overview to see the new counts.')
                        except OSError as e:
                            st.error(f'Unable to save data.csv: {e}')
            except ImportError as e:
                st.error(f'Missing Excel reader dependency: {e}. Install openpyxl for .xlsx or xlrd for .xls.')
            except Exception as e:
                st.error(f'Could not read the uploaded table: {e}')
        elif suffix == '.pdf':
            fingerprint = hashlib.sha256(upload.getvalue()).hexdigest()
            if st.session_state.get('upload_fingerprint') != fingerprint:
                st.session_state['upload_fingerprint'] = fingerprint
                st.session_state.pop('classified_record',None)
            try:
                pages = extract_pdf(upload)
                st.write(f'File: {upload.name} · Pages: {len(pages)} · Extracted characters: {sum(map(len,pages))}')
                if not any(p.strip() for p in pages):
                    st.warning('No selectable text found. OCR is required for scanned PDFs.')
                else:
                    with st.expander('Extracted text preview'):
                        st.text_area('PDF text', numbered(pages,15000),height=300)
                    if st.button('Classify document with Gemini'):
                        try:
                            with st.spinner('Classifying...'):
                                st.session_state['classified_record'] = classify(pages)
                        except Exception as e:
                            st.error(f'Classification error: {e}')
                    if 'classified_record' in st.session_state:
                        record = st.session_state['classified_record']
                        st.write('**Classification rationale:**',record.get('explanation',''))
                        st.write('**Missing information:**',record.get('missing_information',''))
                        with st.form('review_record'):
                            title = st.text_input('Research title', value=str(record.get('title') or upload.name))
                            selected = st.multiselect('Scientific categories', CATEGORIES, default=record.get('categories',[]))
                            record_id = st.text_input('Unique research ID', value='UPLOAD-'+fingerprint[:12].upper())
                            source = st.text_input('Original source URL (optional)')
                            summary = st.text_area('Verified summary',value=str(record.get('summary','')))
                            insight = st.text_area('Verified interpretation',value=str(record.get('insight','')))
                            save = st.form_submit_button('Save verified research to data.csv')
                        if save:
                            if not title.strip() or not record_id.strip():
                                st.error('Title and ID are required.')
                            elif record_id in set(df.id):
                                st.error('This research ID already exists; no duplicate was saved.')
                            elif not selected:
                                st.error('Select at least one category before saving.')
                            else:
                                new = {col:'' for col in df.columns}
                                new.update({'id':record_id.strip(),'name':title.strip(),'topic':str(record.get('topic','')),'category':'; '.join(selected),'gravity':str(record.get('gravity','')),'airflow_max_cm_s':str(record.get('airflow_max_cm_s','')),'oxygen_note':str(record.get('oxygen_note','')),'summary':summary,'insight':insight,'source':source,'doi':str(record.get('doi','')),'evidence_type':str(record.get('evidence_type','')),'flame_spread_rate_mm_s':str(record.get('flame_spread_rate_mm_s',''))})
                                updated = pd.concat([df,pd.DataFrame([new])],ignore_index=True)
                                try:
                                    updated.to_csv(DATA_PATH,index=False)
                                    st.session_state.pop('classified_record',None)
                                    st.success('Saved to data.csv. The Overview will update on rerun.')
                                except OSError as e:
                                    st.error(f'Cannot write data.csv: {e}. Check folder permissions.')
            except Exception as e:
                st.error(f'PDF reading error: {e}')
st.divider()
st.caption('ASTRA-FIRE AI | Research prototype. No NASA affiliation or endorsement implied.')
