import re
with open('src/viper/outputs.py', 'r') as f:
    content = f.read()

content = re.sub(
    r'    __pydantic_extra__: dict\[str, OutputT\] = Field\(\n        init=False,\n        default_factory=dict,\n    \)\n',
    '',
    content
)

with open('src/viper/outputs.py', 'w') as f:
    f.write(content)
