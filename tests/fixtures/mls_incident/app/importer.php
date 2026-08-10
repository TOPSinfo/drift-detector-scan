<?php
// A real-estate importer. The ONLY real third-party API integrations in this repo:
$schools   = $client->get("https://api.greatschools.org/v2/schools?state=MA");
$listings  = file_get_contents("https://www.zillow.com/webservice/GetSearchResults.htm?zws-id=X");
