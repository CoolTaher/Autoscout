navigate(input.url);

wait('a[class*="styles_carCardWrapper"], h4[class*="styles_oops"]');

if (el_exists('h4[class*="styles_oops"]')) {
    dead_page('City not available on Cars24');
} else {
    wait_network_idle({timeout: 800});

    const start_time = Date.now();
    while (Date.now() - start_time < 12000) {
        scroll_to('bottom');
        wait_network_idle({timeout: 600});
    }

}

collect(parse().listings);