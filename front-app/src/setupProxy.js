/* eslint-disable @typescript-eslint/no-var-requires */
/* eslint-disable no-undef */
const { createProxyMiddleware } = require('http-proxy-middleware');
const path = require('path');

filterRegexp = new RegExp('^/course|^/api|^/index.html|^/$');

function filter(pathname, req) {
    return filterRegexp.test(pathname);
}

module.exports = function(app) {
    app.use(
            '/',
            createProxyMiddleware(filter,{
                target: 'http://127.0.0.1:8000',
                secure: false,
                changeOrigin: true})
    );
};