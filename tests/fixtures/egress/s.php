<?php
$ch = curl_init();
curl_setopt($ch, CURLOPT_URL, "https://api.example.com/v1/x");
$out = curl_exec($ch);
$client = new \GuzzleHttp\Client(["base_uri" => "https://api.example.com"]);
