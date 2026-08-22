let listings = [];

$('a[class*="styles_carCardWrapper"]').each((i, el) => {

    let $card = $(el);

    let normal_card = $card.find('div[class*="styles_normalCardWrapper"]');
    if (!normal_card.length) return;

    let name_path = $card.find(
        'div:nth-of-type(2) > div:nth-of-type(1) > div:nth-of-type(1) > div'
    );
    let name_el = name_path.find('> span:nth-of-type(1)');
    let variant_el = name_path.find('> span:nth-of-type(2)');

    let price_el = null;
    $card.find('p').each((i, el) => {
        let text = $(el).text_sane();
        if (text && text.toLowerCase().includes('lakh') && !price_el) {
            price_el = $(el);
        }
    });

    let spec_ul = $card.find('ul').first();
    let spec_divs = spec_ul.find('> div');

    let dealer_el = $card.find('div[class*="styles_badgeContent"] span');
    let address_el = $card.find('div[class*="styles_hubAddress"] p');

    let car_name = name_el.text_sane();
    let year = car_name ? car_name.split(' ')[0] : null;

    // Skip this individual card if essential fields are missing —
    // don't kill the whole job over one bad card
    if (!car_name || !price_el) return;

    listings.push({
        car_name: car_name,
        year: year,
        variant: variant_el.text_sane(),
        price: price_el.text_sane(),
        km_driven: spec_divs.eq(0).text_sane(),
        fuel: spec_divs.eq(1).text_sane(),
        transmission: spec_divs.eq(2).text_sane(),
        location: spec_divs.eq(3).text_sane(),
        car_address: address_el.text_sane(),
        verified_dealer: dealer_el.text_sane(),
        listing_url: $card.attr('href')
    });
});

// Only throw if the ENTIRE page produced nothing — this is the real
// domain-specific failure signal, matching the docs' single-item pattern
if (listings.length === 0) {
    throw new Error('No car listings extracted — page structure may have changed');
}

return { listings: listings };