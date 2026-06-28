from bs4 import BeautifulSoup

with open('templates/index.html', 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

# Extract sidebar
sidebar = soup.find('aside', class_='sidebar') or soup.find('nav', class_='sidebar') or soup.find(attrs={'id': 'sidebar'})
# Actually let's search for the aside
sidebar_tag = soup.find('aside')
if not sidebar_tag:
    # Try finding by looking at div with sidebar class
    sidebar_tag = soup.find(class_='sidebar')

print("Sidebar tag:", sidebar_tag.name if sidebar_tag else None)

# Extract all view-pane sections
view_panes = soup.find_all('section', class_='view-pane')
print(f"Found {len(view_panes)} view panes")

# Write sidebar
if sidebar_tag:
    with open('templates/components/sidebar.html', 'w', encoding='utf-8') as f:
        f.write(str(sidebar_tag))
    sidebar_tag.replace_with("\n{% include 'components/sidebar.html' %}\n")

# Write views
if view_panes:
    views_html = ""
    for sec in view_panes:
        views_html += str(sec) + "\n\n"
        sec.replace_with('')
    with open('templates/components/views.html', 'w', encoding='utf-8') as f:
        f.write(views_html)
    
    # Find where to insert include - after dashboard-content header or inside it
    dashboard_content = soup.find('main') or soup.find(class_='dashboard-content')
    if dashboard_content:
        dashboard_content.append("\n{% include 'components/views.html' %}\n")
    else:
        # Just find where the body ends and insert before body close
        body = soup.find('body')
        if body:
            body.append("\n{% include 'components/views.html' %}\n")

html_out = str(soup)

with open('templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html_out)
    
print("Done!")
