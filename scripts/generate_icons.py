import os

icons_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app', 'static', 'icons')
os.makedirs(icons_dir, exist_ok=True)

# Clean old files
for f in os.listdir(icons_dir):
    fp = os.path.join(icons_dir, f)
    if os.path.isfile(fp) and not f.endswith('.py'):
        os.remove(fp)

svg_content = '''<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 192 192">
  <rect width="192" height="192" rx="32" fill="#2563eb"/>
  <g transform="translate(96,96)">
    <rect x="-40" y="-30" width="80" height="60" rx="6" fill="white" opacity="0.95"/>
    <polygon points="-44,-30 0,-44 44,-30 0,-16" fill="white" opacity="0.7"/>
    <line x1="0" y1="-14" x2="0" y2="12" stroke="#2563eb" stroke-width="6" stroke-linecap="round"/>
    <polyline points="-12,0 0,12 12,0" stroke="#2563eb" stroke-width="6" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
  </g>
</svg>'''

for size in [192, 512]:
    filename = f'icon-{size}x{size}.svg'
    content = svg_content.format(size=size)
    with open(os.path.join(icons_dir, filename), 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'Created: {filename}')

print('Icons created successfully')