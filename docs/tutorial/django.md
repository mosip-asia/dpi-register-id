# Django Modular App Standard

In this AIT Brainlab standard, we develop **reusable Django app modules**, not monolithic Django websites. 

---

## Directory Structure

```
├── django_manage.py             # Root management script
├── src/
│   ├── django_core/             # Development host configuration
│   │   ├── __init__.py
│   │   ├── asgi.py
│   │   ├── settings.py          # Environment-aware settings
│   │   ├── urls.py              # Root router
│   │   └── wsgi.py
│   └── django_module/           # Example reusable modular app
│       ├── __init__.py
│       ├── admin.py
│       ├── apps.py
│       ├── migrations/
│       ├── models.py
│       ├── tests.py
│       └── views.py
```

- **`src/django_core/`**: Minimal harness used for local development and testing. Production deployments will plug your app into their own Django host or service framework.
- **`src/django_module/`**: The actual modular app that should remain standalone and decoupled.

---

## Common Management Commands

Use `uv run django_manage.py` to execute Django commands:

```bash
# Run system integrity check
uv run django_manage.py check

# Start development server
uv run django_manage.py runserver 0.0.0.0:8000

# Make migrations for your module
uv run django_manage.py makemigrations django_module

# Apply database migrations
uv run django_manage.py migrate

# Create superuser
uv run django_manage.py createsuperuser
```

---

## Creating a New App Module

1. Generate the app boilerplate inside `src/`:
   ```bash
   uv run django_manage.py startapp myapp src/myapp
   ```

2. Register the module in `src/django_core/settings.py`:
   ```python
   INSTALLED_APPS = [
       'django.contrib.admin',
       'django.contrib.auth',
       'django.contrib.contenttypes',
       'django.contrib.sessions',
       'django.contrib.messages',
       'django.contrib.staticfiles',
       'myapp',  # <-- Add your app here
   ]
   ```

3. Route URLs in `src/django_core/urls.py`:
   ```python
   from django.contrib import admin
   from django.urls import include, path

   urlpatterns = [
       path('admin/', admin.site.urls),
       path('myapp/', include('myapp.urls')),  # <-- Add route here
   ]
   ```

---

## Environment Integration

Settings dynamically adapt based on `.env`:
- **`DEBUG`**: Automatically `True` in `dev`, and `False` in `stg` / `prod`.
- **`ALLOWED_HOSTS`**: Controlled via `ALLOWED_HOSTS` in `.env` (defaults to `*` in `dev`).
- **`DJANGO_SECRET_KEY`**: Set via `DJANGO_SECRET_KEY` in `.env`.
