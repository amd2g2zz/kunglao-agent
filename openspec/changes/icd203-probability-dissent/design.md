# Design — icd203-probability-dissent
7 档 enum 顺序遵循 ICD-203: almost_certain > very_likely > likely > roughly_even > unlikely > very_unlikely > almost_no_chance。旧 3 档映射: confirmed->almost_certain, highly_likely->very_likely, suspected->roughly_even (PRD Open Question #2 答案)。validate_confidence 接受新旧值; 旧值自动映射后返回新值。dissent 写 fact 内 ```dissent yaml 块(不建独立文件, 保持单文件可溯)。
