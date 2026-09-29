import i18n from "i18next";
import { initReactI18next } from "react-i18next";

export function normalizeLocale(locale: string): "en" | "fr" {
  const language = locale.toLowerCase().split(/[-_]/)[0];
  return language === "fr" ? "fr" : "en";
}

void i18n.use(initReactI18next).init({
  lng: "en",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  resources: {
    en: {
      translation: {
        loading: "Connecting to Fred…",
        back: "Back",
        retry: "Retry",
        unknownRoute: "This page does not exist.",
        evaluations: {
          title: "Evaluations",
          count_one: "{{count}} evaluation",
          count_other: "{{count}} evaluations",
          loading: "Loading evaluations…",
          empty: "No evaluation yet for this team.",
          loadFailed: "The evaluations could not be loaded.",
          notGranted:
            "This team does not have access to the evaluation application.",
          name: "Name",
          version: "Version",
          cases: "Cases",
          completeness: "Completeness",
          author: "Author",
          created: "Created",
          complete: "Complete",
          minimal: "Minimal",
        },
      },
    },
    fr: {
      translation: {
        loading: "Connexion à Fred…",
        back: "Retour",
        retry: "Réessayer",
        unknownRoute: "Cette page n'existe pas.",
        evaluations: {
          title: "Évaluations",
          count_one: "{{count}} évaluation",
          count_other: "{{count}} évaluations",
          loading: "Chargement des évaluations…",
          empty: "Aucune évaluation pour cette équipe.",
          loadFailed: "Les évaluations n'ont pas pu être chargées.",
          notGranted:
            "Cette équipe n'a pas accès à l'application d'évaluation.",
          name: "Nom",
          version: "Version",
          cases: "Cas",
          completeness: "Complétude",
          author: "Auteur",
          created: "Créée le",
          complete: "Complète",
          minimal: "Minimale",
        },
      },
    },
  },
});

export default i18n;
