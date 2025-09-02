// import 'babel-polyfill';
import React from 'react';
import ReactDOM from 'react-dom';
import * as _ from 'lodash';
import App from 'app/App';

// Make lodash available globally for MapLibre GL JS
window._ = _;

ReactDOM.render(React.createElement(App), document.getElementById('root'));
