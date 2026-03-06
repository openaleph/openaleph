import React from 'react';
import { connect } from 'react-redux';
import { Country as VLCountry, CountrySelect } from 'react-ftm';
import { wordList } from 'react-ftm/utils';
import { selectLocale, selectModel } from 'selectors';

import './Country.scss';

const mapStateToProps = (state) => {
  const model = selectModel(state);
  const locale = selectLocale(state);

  return { fullList: model.types.country.values, locale };
};

function CountryFlag({ code }) {
  if (!code) return null;
  if (code.toLowerCase() === 'zz') {
    return (
      <span className="CountryFlag CountryFlag--global">
        <svg viewBox="0 0 4 3" width="1.33em" height="1em">
          <rect width="4" height="3" fill="var(--aleph-accent-color)" />
          <g transform="translate(2, 1.5) scale(0.085)" fill="white">
            <path d="M0-12c-6.63 0-12 5.37-12 12s5.37 12 12 12 12-5.37 12-12S6.63-12 0-12zm-1.2 21.53c-4.74-.59-8.4-4.62-8.4-9.53 0-.74.1-1.45.25-2.15L-1.2 6v1.2c0 1.32 1.08 2.4 2.4 2.4v2.33zm8.28-3.05c-.31-.97-1.2-1.67-2.28-1.67h-1.2V1.2c0-.66-.54-1.2-1.2-1.2H-3.6v-2.4H-1.2c.66 0 1.2-.54 1.2-1.2V-6h2.4c1.32 0 2.4-1.08 2.4-2.4v-.49C8.32-7.46 10.8-4.02 10.8 0c0 2.5-.96 4.76-2.52 6.48z" />
          </g>
        </svg>
      </span>
    );
  }
  return <span className={`CountryFlag fi fi-${code.toLowerCase()}`} />;
}

function CountryLabel({ code, fullList, locale, flag = false }) {
  if (!code) return null;
  return (
    <span>
      {flag && <CountryFlag code={code} />}
      <VLCountry.Label code={code} fullList={fullList} locale={locale} />
    </span>
  );
}

function CountryNameWithFlag({ code, fullList, locale }) {
  return <CountryLabel code={code} fullList={fullList} locale={locale} flag />;
}

function CountryListWithFlags({ codes, truncate = Infinity, fullList, locale }) {
  if (!codes) return null;

  let names = codes.map((code) => (
    <span key={code}>
      <CountryFlag code={code} />
      <VLCountry.Label code={code} fullList={fullList} locale={locale} />
    </span>
  ));

  if (names.length > truncate) {
    names = [...names.slice(0, truncate), '…'];
  }
  return wordList(names, ', ');
}

class Country {
  static Label = connect(mapStateToProps)(CountryLabel);

  static Name = connect(mapStateToProps)(CountryNameWithFlag);

  static List = connect(mapStateToProps)(CountryListWithFlags);

  static MultiSelect = connect(mapStateToProps)(CountrySelect);
}

export default Country;
