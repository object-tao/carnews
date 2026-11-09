document.addEventListener('DOMContentLoaded', () => {
  const country = document.querySelector('#cgr-country');
  const port = document.querySelector('#cgr-port');
  if (country && port) country.addEventListener('change', () => {
    port.value = '';
    country.form.requestSubmit();
  });
});
