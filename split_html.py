from bs4 import BeautifulSoup

with open('static/index.html', 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

auth_container = soup.find(id='auth-container')
if auth_container:
    with open('templates/components/auth.html', 'w', encoding='utf-8') as f:
        f.write(str(auth_container))
    auth_container.replace_with("{% include 'components/auth.html' %}")

sidebar = soup.find('nav', class_='sidebar')
if sidebar:
    with open('templates/components/sidebar.html', 'w', encoding='utf-8') as f:
        f.write(str(sidebar))
    sidebar.replace_with("{% include 'components/sidebar.html' %}")

views_container = soup.find('main', class_='dashboard-content')
if views_container:
    # We can put the whole dashboard-content into a views file, or keep it and extract sections
    views_html = ""
    sections = views_container.find_all('section', class_='view-pane')
    for sec in sections:
        views_html += str(sec) + "\n\n"
        sec.decompose()
        
    with open('templates/components/views.html', 'w', encoding='utf-8') as f:
        f.write(views_html)
    
    # insert include tag
    header = views_container.find('header')
    if header:
        header.insert_after("{% include 'components/views.html' %}")
    else:
        views_container.append("{% include 'components/views.html' %}")

modals = soup.find_all('div', class_='modal')
if modals:
    modals_html = ""
    for m in modals:
        modals_html += str(m) + "\n\n"
        m.replace_with('')
    
    # replace the first modal with include
    with open('templates/components/modals.html', 'w', encoding='utf-8') as f:
        f.write(modals_html)
    
    # Add include just before closing body
    body = soup.find('body')
    if body:
        # We can just insert it at the end
        pass

# Add modals include at the end of body
body = soup.find('body')
if body:
    body.append("{% include 'components/modals.html' %}")

# Also replace <script src="app.js"></script> with <script type="module" src="{{ url_for('static', filename='js/main.js') }}"></script>
script_app = soup.find('script', src='app.js')
if script_app:
    script_app['src'] = "{{ url_for('static', filename='js/main.js') }}"
    script_app['type'] = 'module'
    
# Update style.css href
link_css = soup.find('link', href='style.css')
if link_css:
    link_css['href'] = "{{ url_for('static', filename='style.css') }}"

html_out = str(soup)
html_out = html_out.replace("&lt;% include", "{% include").replace("%&gt;", "%}")

with open('templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html_out)

print("Done HTML!")
