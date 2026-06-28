import re

html = open('templates/index.html').read()
scripts = """
<script src="{{ url_for('static', filename='js/main.js') }}"></script>
<script src="{{ url_for('static', filename='js/invoices.js') }}"></script>
<script src="{{ url_for('static', filename='js/deposits_loans.js') }}"></script>
<script src="{{ url_for('static', filename='js/stock.js') }}"></script>
<script src="{{ url_for('static', filename='js/agreements.js') }}"></script>
<script src="{{ url_for('static', filename='js/fundraisers.js') }}"></script>
<script src="{{ url_for('static', filename='js/chat.js') }}"></script>
<script src="{{ url_for('static', filename='js/ai_console.js') }}"></script>
<script src="{{ url_for('static', filename='js/rewards.js') }}"></script>
<script src="{{ url_for('static', filename='js/settings.js') }}"></script>
<script src="{{ url_for('static', filename='js/admin.js') }}"></script>
"""

html = re.sub(r'<script.*js/main\.js.*?</script>', scripts, html, flags=re.DOTALL)

with open('templates/index.html', 'w') as f:
    f.write(html)
