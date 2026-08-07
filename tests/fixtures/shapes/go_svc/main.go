package main

import "net/http"

// A Go service that calls a third-party API. We have NO egress-signal rules for Go,
// so the scanner cannot see how this request is built — it must say so, not pass.
func fetchOrders(base string) (*http.Response, error) {
	url := base + "/orders/2026-01-01/orders"
	return http.Get(url)
}
