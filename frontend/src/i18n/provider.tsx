import { useCallback, useMemo, useState } from 'react'
import {
  I18nContext,
  DEFAULT_LANGUAGE,
  resources,
  getNestedValue,
  interpolate,
  type Language,
  type Namespace,
} from './context'

export const I18nProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [language, setLanguage] = useState<Language>(() => {
    const stored = typeof window !== 'undefined' ? localStorage.getItem('i18n-lang') : null
    return (stored as Language) || DEFAULT_LANGUAGE
  })

  const changeLanguage = useCallback((lang: Language) => {
    setLanguage(lang)
    if (typeof window !== 'undefined') {
      localStorage.setItem('i18n-lang', lang)
      document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en'
    }
  }, [])

  const t = useCallback(
    (key: string, options?: Record<string, unknown>) => {
      const ns: Namespace = 'translation'
      const value = getNestedValue(resources[language][ns], key)
      if (typeof value !== 'string') return key
      return interpolate(value, options)
    },
    [language]
  )

  const value = useMemo(
    () => ({ language, changeLanguage, t }),
    [language, changeLanguage, t]
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}
