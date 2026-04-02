/**
 * Cloudflare Worker Proxy for Sodeom Search Engine
 * 
 * This worker acts as a proxy to bypass PythonAnywhere whitelist restrictions.
 * Deploy this to Cloudflare Workers and use the URL as your proxy endpoint.
 * 
 * Deployment:
 * 1. Go to https://dash.cloudflare.com/
 * 2. Click "Workers & Pages"
 * 3. Create a new Worker
 * 4. Paste this code
 * 5. Deploy and copy the worker URL (e.g., https://your-proxy.workers.dev)
 */

export default {
  async fetch(request, env, ctx) {
    // Handle CORS preflight requests
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type, Authorization, User-Agent',
          'Access-Control-Max-Age': '86400',
        },
      });
    }

    try {
      const url = new URL(request.url);
      
      // Get target URL from query parameter
      const targetUrl = url.searchParams.get('url');
      
      if (!targetUrl) {
        return new Response(
          JSON.stringify({ 
            error: 'Missing required parameter: url',
            usage: 'https://your-worker.workers.dev?url=https://example.com'
          }), 
          { 
            status: 400,
            headers: { 'Content-Type': 'application/json' }
          }
        );
      }

      // Validate URL
      let target;
      try {
        target = new URL(targetUrl);
      } catch (e) {
        return new Response(
          JSON.stringify({ error: 'Invalid URL provided' }), 
          { 
            status: 400,
            headers: { 'Content-Type': 'application/json' }
          }
        );
      }

      // Only allow HTTP/HTTPS
      if (!['http:', 'https:'].includes(target.protocol)) {
        return new Response(
          JSON.stringify({ error: 'Only HTTP/HTTPS URLs are allowed' }), 
          { 
            status: 400,
            headers: { 'Content-Type': 'application/json' }
          }
        );
      }

      // Prepare headers for the proxied request
      const proxyHeaders = new Headers();
      
      // Copy important headers from original request
      const headersToForward = [
        'Accept',
        'Accept-Language',
        'Content-Type',
        'Referer',
      ];

      for (const header of headersToForward) {
        const value = request.headers.get(header);
        if (value) {
          proxyHeaders.set(header, value);
        }
      }

      // Set a realistic User-Agent
      proxyHeaders.set('User-Agent', 
        request.headers.get('User-Agent') || 
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
      );

      // Make the proxied request
      const proxyRequest = new Request(targetUrl, {
        method: request.method,
        headers: proxyHeaders,
        body: request.method !== 'GET' && request.method !== 'HEAD' ? await request.arrayBuffer() : null,
        redirect: 'follow',
      });

      const response = await fetch(proxyRequest);

      // Create new response with CORS headers
      const responseHeaders = new Headers(response.headers);
      responseHeaders.set('Access-Control-Allow-Origin', '*');
      responseHeaders.set('Access-Control-Expose-Headers', '*');
      
      // Remove headers that might cause issues
      responseHeaders.delete('Content-Security-Policy');
      responseHeaders.delete('X-Frame-Options');

      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: responseHeaders,
      });

    } catch (error) {
      return new Response(
        JSON.stringify({ 
          error: 'Proxy request failed', 
          message: error.message 
        }), 
        { 
          status: 500,
          headers: { 
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
          }
        }
      );
    }
  },
};
