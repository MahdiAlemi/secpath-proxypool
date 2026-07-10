localStorage.removeItem('token');

async function doLogin(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const errorBox = document.querySelector('.error');
  button.disabled = true;
  button.textContent = 'Signing in...';

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
    errorBox.textContent = response.status === 429
      ? 'Too many failed attempts. Try again later.'
      : 'Invalid credentials or expired form. Refresh and try again.';
    errorBox.style.display = 'block';
  } catch (_error) {
    errorBox.textContent = 'Login failed';
    errorBox.style.display = 'block';
  } finally {
    button.disabled = false;
    button.textContent = 'Sign in';
  }
}
