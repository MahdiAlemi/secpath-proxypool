localStorage.removeItem('token');

async function doLogin(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const errorBox = document.querySelector('.error');
  const original = button.innerHTML;
  button.disabled = true;
  button.innerHTML = '<span>Signing in…</span><span aria-hidden="true">↻</span>';
  if (errorBox) {
    errorBox.hidden = true;
    errorBox.textContent = '';
  }

  try {
    const response = await fetch('/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: new URLSearchParams(new FormData(form)).toString(),
      credentials: 'same-origin',
      redirect: 'follow'
    });

    if (response.ok && response.url && !response.url.endsWith('/login')) {
      window.location.assign(response.url);
      return;
    }
    if (errorBox) {
      errorBox.textContent = response.status === 429
        ? 'Too many failed attempts. Try again later.'
        : 'The username or password is not valid.';
      errorBox.hidden = false;
    }
  } catch (_error) {
    if (errorBox) {
      errorBox.textContent = 'The dashboard could not be reached. Check the local service and try again.';
      errorBox.hidden = false;
    }
  } finally {
    button.disabled = false;
    button.innerHTML = original;
  }
}
