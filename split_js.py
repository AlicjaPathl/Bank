import re

js_content = open('static/app.js').read()
sections = re.split(r'// ================================================================\n//  MODULE: (.*?)\n// ================================================================', js_content)

main_content = sections[0]
modules = {}

for i in range(1, len(sections), 2):
    title = sections[i].strip()
    content = sections[i+1]
    modules[title] = content

# Write main content to main.js (we won't use ES modules to avoid scoping hell, just separate scripts)
with open('static/js/main.js', 'w') as f:
    f.write(main_content)

for title, content in modules.items():
    filename = {
        'FAKTURY': 'invoices.js',
        'LOKATY I KREDYTY': 'deposits_loans.js',
        'GIEŁDA': 'stock.js',
        'UMOWY': 'agreements.js',
        'ZBIÓRKI': 'fundraisers.js',
        'CZAT E2E (RSA + AES via Web Crypto)': 'chat.js',
        'KONSOLA AI': 'ai_console.js',
        'NAGRODY': 'rewards.js',
        'USTAWIENIA': 'settings.js',
        'PANEL ADMINA': 'admin.js'
    }.get(title, 'other.js')
    
    with open(f'static/js/{filename}', 'w') as f:
        f.write(f"// MODULE: {title}\n")
        f.write(content)

print("Done JS split!")
