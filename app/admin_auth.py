def ensure_admin_exists(db: Session):
    """
    Ensures exactly one admin exists.
    Admin credentials come ONLY from ENV.
    Safe to run on every startup.
    """

    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")

    if not admin_email or not admin_password:
        # Do not crash production if env vars are missing
        return

    admin = (
        db.query(User)
        .filter(User.email == admin_email, User.role == "admin")
        .first()
    )

    if admin:
        return  # already exists

    admin = User(
        email=admin_email,
        hashed_password=hash_password(admin_password),  # ✅ ONLY THIS
        role="admin",
        is_active=True,
    )

    db.add(admin)
    db.commit()

    print("✅ Admin user created from environment variables")
