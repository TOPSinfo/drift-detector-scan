# httprb (the `http` gem) egress — the shape lineofflight/peddler uses.
# Deliberately contains NO Net::HTTP, RestClient, HTTParty or Faraday, so a sink match
# here can only come from the HTTP.$M pattern this fixture exists to prove.
require "http"

response = HTTP.post(URL, form: params)
document = HTTP.get(download_url)
inflated = HTTP.use(:auto_inflate).get(document_url)
