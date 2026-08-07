<?php
function send($u) {
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $u);
    return curl_exec($ch);
}
