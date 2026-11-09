<!-- Bu sablon PR acinca kendiliginden dolar. Gereksiz maddeyi sil. -->

## Ne degisiyor, neden?

## Canliya almadan once

- [ ] `check` (test, panel, docker) yesil
- [ ] Hatti/render'i/bagimliligi/workflow'u etkiliyorsa `render-smoke` yesil ve artifact'taki video izlendi
- [ ] Yeni senaryo ise: `python -m editorial.authored` temiz ve `content/plan.md`'ye eklendi
- [ ] Sir, token ya da anahtar eklenmedi (sirlar yalniz GitHub Secrets / sunucudaki `secrets/` icinde)
- [ ] `panel/` degistiyse birlestirdikten sonra sunucuda `./update.sh` calistirilacak

## Geri alma

<!-- Sorun cikarsa: GitHub'da bu PR'in "Revert" dugmesi. panel/ ise sunucuda update.sh kendiliginden geri alir. -->
