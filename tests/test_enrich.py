from realestate.enrich import (
    extract_emails,
    extract_phones,
    is_pr_phone,
    looks_like_realtor,
)


def test_extract_phones_formats():
    text = """
    Llamar (787) 717-0187 o (305) 297-0501.
    También 939.555.1234 y 7875551212.
    No esto: 1-800-flowers (letters)
    """
    phones = extract_phones(text)
    assert "787-717-0187" in phones
    assert "305-297-0501" in phones
    assert "939-555-1234" in phones
    assert "787-555-1212" in phones


def test_extract_phones_dedup_and_order():
    text = "Llame (787) 555-0100 o 787-555-0100 o 787.555.0100"
    phones = extract_phones(text)
    assert phones == ["787-555-0100"]


def test_extract_emails():
    text = "Contacto: Owner@Example.COM y también juan.perez+pr@gmail.com  end."
    emails = extract_emails(text)
    assert emails == ["owner@example.com", "juan.perez+pr@gmail.com"]


def test_is_pr_phone():
    assert is_pr_phone("787-555-0100")
    assert is_pr_phone("939-555-0100")
    assert not is_pr_phone("305-555-0100")


def test_looks_like_realtor():
    assert looks_like_realtor("KASA CANDAL REALTY") == (True, "realty")
    assert looks_like_realtor("MICORREDOR.COM Lic#16784")[0] is True
    assert looks_like_realtor("Anibal Beauchamp") == (False, None)
    assert looks_like_realtor("Juan Pérez") == (False, None)
    assert looks_like_realtor(None) == (False, None)
    assert looks_like_realtor("Owners Realty Group") == (True, "realty")


def test_looks_like_realtor_llc_inc():
    assert looks_like_realtor("Casa Sol LLC")[0] is True
    assert looks_like_realtor("Properties Inc")[0] is True


def test_looks_like_realtor_pr_license():
    is_r, kw = looks_like_realtor("Ricardo Cofiño L-5064 Genesis Paola Co")
    assert is_r is True
    assert kw == "license:L-5064"
    is_r, kw = looks_like_realtor("Property Concepts Commercial Lic. E-70")
    assert is_r is True  # caught by 'lic.' keyword
    is_r, kw = looks_like_realtor("Maria Rodriguez E-12345")
    assert is_r is True
    assert kw == "license:E-12345"


def test_looks_like_realtor_keller_williams():
    assert looks_like_realtor("Keller Williams Realty PR")[0] is True
    is_r, kw = looks_like_realtor("KW Boricua")
    assert is_r is True
    assert kw == "abbrev:KW"
    is_r, kw = looks_like_realtor("Maria KW")  # standalone KW
    assert is_r is True
    # Should NOT trigger on names containing 'kw' as substring (e.g. 'Skowron')
    assert looks_like_realtor("Skowron")[0] is False


def test_looks_like_realtor_other_big_brokerages():
    assert looks_like_realtor("ReMax Premier")[0] is True
    assert looks_like_realtor("RE/MAX Caribe")[0] is True
    assert looks_like_realtor("Century 21 Top")[0] is True
    assert looks_like_realtor("Coldwell Banker")[0] is True
    assert looks_like_realtor("eXp Realty PR")[0] is True
    assert looks_like_realtor("Compass Real Estate")[0] is True
