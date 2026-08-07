class A {
  void f() throws Exception {
    HttpClient c = HttpClient.newHttpClient();
    HttpRequest r = HttpRequest.newBuilder().uri(URI.create("https://api.example.com/v1/x")).build();
    URLConnection u = new URL("https://api.example.com/v1/y").openConnection();
    String s = restTemplate.getForObject("https://api.example.com/v1/z", String.class);
  }
}
