from bs4 import BeautifulSoup
import requests

r = requests.get('https://fileinfo.com/filetypes/audio')

a = []
soup = BeautifulSoup(r.content, 'lxml')
for row in soup.findAll('td'):
    format = row.find('a')
    if format is not None:
        a.append(format.text[1:].lower())

with open('..\\..\\src\\audio_format_list.txt', 'w') as f:
    f.write('\n'.join(a) + '\n')
