<?php
class OrdersApi {
    public function searchOrders() {
        $resource_path = '/orders/2026-01-01/orders';
        $url = $this->config->getHost() . $resource_path;
        return $url;
    }
}
