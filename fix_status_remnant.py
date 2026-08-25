with open('inventory/models.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find line 820 area
lines = content.split('\n')
for i, l in enumerate(lines[810:830], start=811):
    print(f"{i:3d}: {l}")
