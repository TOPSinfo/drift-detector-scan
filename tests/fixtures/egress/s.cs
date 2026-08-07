class A {
  async Task F() {
    var c = new HttpClient();
    var r = await c.GetAsync("https://api.example.com/v1/x");
    var w = WebRequest.Create("https://api.example.com/v1/y");
    var p = await c.PostAsync(url, content);
  }
}
