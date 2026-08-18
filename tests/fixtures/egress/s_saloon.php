<?php
// Saloon connector egress — the shape jlevers/selling-partner-api uses 350 times.
// Deliberately contains NO curl_exec and NO `new \GuzzleHttp\Client`, so a sink match
// here can only come from the connector/client patterns this fixture exists to prove.
namespace App;

use Saloon\Http\Connector;

class Api
{
    public function getOrders($request)
    {
        return $this->connector->send($request);
    }

    public function legacy($request, $options)
    {
        return $this->client->send($this->createGuzzleRequest($request, $options));
    }
}
