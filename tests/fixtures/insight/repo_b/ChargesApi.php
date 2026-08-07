<?php
class ChargesApi {
    public function create() {
        $resource_path = '/v1/charges';
        $url = $this->config->getHost() . $resource_path;
        return $url;
    }
}
