package main
import "net/http"
func main() {
	resp, _ := http.Get("https://api.example.com/v1/x")
	req, _ := http.NewRequest("GET", url, nil)
	res, _ := client.Do(req)
	http.Post(url, "application/json", body)
	_ = resp; _ = res
}
