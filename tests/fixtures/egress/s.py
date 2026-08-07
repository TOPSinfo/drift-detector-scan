import requests, httpx, urllib.request
r = requests.get("https://api.example.com/v1/x")
p = requests.post(url, json=body)
h = httpx.get("https://api.example.com/v1/y")
u = urllib.request.urlopen("https://api.example.com/v1/z")
s = requests.Session()
