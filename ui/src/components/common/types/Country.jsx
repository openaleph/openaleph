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
