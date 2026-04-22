import {
  render as rtlRender,
  RenderOptions as RtlRenderOptions,
} from '@testing-library/react';
import { IntlProvider } from 'react-intl';
import { createStore } from 'redux';
import { Provider } from 'react-redux';
import { FunctionComponent, ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { defaultModel } from '@alephdata/followthemoney';
import rootReducer from 'reducers';
import translations from 'content/translations.json';

type DefaultLocale = 'en';
type Locale = keyof typeof translations | DefaultLocale;
type RenderOptions = RtlRenderOptions & { locale?: Locale };

const store = createStore(
  rootReducer,
  { metadata: { model: defaultModel } },
);

function render(
  ui: ReactElement,
  { locale = 'en', ...renderOptions }: RenderOptions = {}
) {
  const Wrapper: FunctionComponent = ({ children }) => {
    let messages =
      locale in translations
        ? translations[locale as Exclude<Locale, DefaultLocale>]
        : undefined;

    return (
      <Provider store={store}>
        <MemoryRouter>
          <IntlProvider key={locale} locale={locale} messages={messages}>
              {children}
          </IntlProvider>
        </MemoryRouter>
      </Provider>
    );
  };

  return rtlRender(ui, { wrapper: Wrapper, ...renderOptions });
}

export * from '@testing-library/react';
export { render };
