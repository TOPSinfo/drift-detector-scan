require 'net/http'
r = Net::HTTP.get(URI("https://api.example.com/v1/x"))
Net::HTTP.start(host) { |http| http.request(req) }
c = RestClient.get("https://api.example.com/v1/y")
h = HTTParty.get("https://api.example.com/v1/z")
f = Faraday.new(url: "https://api.example.com")
