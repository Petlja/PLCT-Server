import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { CookiesProvider } from 'react-cookie';
import { BrowserRouter } from 'react-router-dom';
import { vi, beforeEach, afterEach } from 'vitest';
import App from './App';

beforeEach(() => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify([]), { status: 200, headers: { 'Content-Type': 'application/json' } })
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

test('renders app', async () => {
  render(
    <CookiesProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </CookiesProvider>
  );

  await waitFor(() => {
    expect(document.body).toBeTruthy();
  });
});
