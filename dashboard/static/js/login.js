if (localStorage.getItem('token')) {
  window.location.href = '/';
}
async function doLogin(e) {
  e.preventDefault();
  const username = document.querySelector('input[name="username"]').value;
  const password = document.querySelector('input[name="password"]').value;
  const btn = document.querySelector('button');
  btn.disabled = true;
  btn.textContent = 'Loading...';
  try {
    const res = await fetch('/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: 'username=' + encodeURIComponent(username) + '&password=' + encodeURIComponent(password),
      credentials: 'include'
    });
    if (res.ok || res.redirected) {
      const tokenRes = await fetch('/api/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username, password})
      });
      const data = await tokenRes.json();
      if (data.success && data.token) {
        localStorage.setItem('token', data.token);
      }
      window.location.href = res.url || '/';
    } else {
      document.querySelector('.error').textContent = 'Invalid credentials';
      btn.disabled = false;
      btn.textContent = 'Sign in';
    }
  } catch(err) {
    document.querySelector('.error').textContent = 'Login failed';
    btn.disabled = false;
    btn.textContent = 'Sign in';
  }
}
