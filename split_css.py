import os
import re

css_content = open('static/style.css').read()
blocks = re.split(r'/\* ================= (.*?) ================= \*/', css_content)

files_map = {
    'DESIGN SYSTEM / ZMIENNE': 'variables.css',
    'RESET & BAZA': 'base.css',
    'WIZUALNE EFEKTY W TLE': 'base.css',
    'ELEMENTY SZKLANE (GLASSMORPHISM)': 'base.css',
    'PRZYCISKI & FORMY': 'components.css',
    'AUTORYZACJA': 'auth.css',
    'KOKPIT (DASHBOARD) LAYOUT': 'dashboard.css',
    'KARTY / WIDŻETY': 'components.css',
    'WIDOK KARTY KREDYTOWEJ': 'components.css',
    'TABELE': 'components.css',
    'MODALE (POP-UPY)': 'components.css',
    'ZAKŁADKI (TABS)': 'components.css',
    'SYSTEM POWIADOMIEŃ (TOAST)': 'components.css',
    'CZAT / KONSOLA AI': 'components.css',
    'ZARZĄDZANIE WIDOKAMI (SPA)': 'dashboard.css',
    'RESPONSYWNOŚĆ (MOBILE)': 'layout.css'
}

current_section = "variables.css"
output_files = {v: "" for v in set(files_map.values())}
output_files['layout.css'] = ""
output_files['main.css'] = ""

for i in range(1, len(blocks), 2):
    title = blocks[i].strip()
    content = blocks[i+1]
    
    file_name = files_map.get(title, 'components.css')
    output_files[file_name] += f"/* ================= {title} ================= */\n{content}\n"

for fname, content in output_files.items():
    if fname == 'main.css': continue
    if content.strip():
        with open(f'static/css/{fname}', 'w') as f:
            f.write(content)

with open('static/style.css', 'w') as f:
    f.write('@import url("css/variables.css");\n')
    f.write('@import url("css/base.css");\n')
    f.write('@import url("css/layout.css");\n')
    f.write('@import url("css/auth.css");\n')
    f.write('@import url("css/dashboard.css");\n')
    f.write('@import url("css/components.css");\n')

print("Done CSS!")
