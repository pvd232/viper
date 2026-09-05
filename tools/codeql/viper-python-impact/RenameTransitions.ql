/**
 * @name VIPER Python rename transitions
 * @description Emits import-bound reference syntax even when a target declaration is absent.
 * @kind table
 * @id viper/python-impact/rename-transitions
 */

import python
import Nodes

/** Find the nearest represented declaration containing one reference. */
private predicate referenceOwner(
  AstNode evidence,
  AstNode source,
  AstNode sourceBinding
) {
  source.contains(evidence) and
  exists(string kind, string name |
    declaration(source, sourceBinding, kind, name)
  ) and
  not exists(AstNode nearer, AstNode nearerBinding, string kind, string name |
    nearer.contains(evidence) and
    source.contains(nearer) and
    source != nearer and
    declaration(nearer, nearerBinding, kind, name)
  )
}

/** Classify the operation performed through one imported reference. */
private string referenceKind(Expr reference) {
  exists(Call call | call.getFunc() = reference) and result = "calls"
  or
  not exists(Call call | call.getFunc() = reference) and
  exists(Attribute attribute |
    attribute = reference and
    attribute.getCtx() instanceof Store
  ) and result = "writes"
  or
  not exists(Call call | call.getFunc() = reference) and
  exists(Attribute attribute |
    attribute = reference and
    attribute.getCtx() instanceof AugStore
  ) and result = "writes"
  or
  not exists(Call call | call.getFunc() = reference) and
  exists(Name name | name = reference and name.isDefinition()) and
  result = "writes"
  or
  not exists(Call call | call.getFunc() = reference) and
  not exists(Attribute attribute |
    attribute = reference and
    (attribute.getCtx() instanceof Store or attribute.getCtx() instanceof AugStore)
  ) and
  not exists(Name name | name = reference and name.isDefinition()) and
  result = "reads"
}

/** Match `import module as alias; alias.symbol`. */
private predicate moduleAttributeReference(
  Expr evidence,
  string targetModule,
  string targetSymbol,
  string kind,
  string bindingForm,
  string resolution
) {
  exists(Alias imported, ImportExpr importExpr, Name aliasName, Name use, Attribute attribute |
    imported.getValue() = importExpr and
    aliasName = imported.getAsname() and
    use.getVariable() = aliasName.getVariable() and
    attribute.getObject() = use and
    evidence = attribute and
    targetModule = importExpr.getImportedModuleName() and
    targetSymbol = attribute.getName() and
    kind = referenceKind(attribute) and
    bindingForm = "module_alias" and
    resolution = "resolved"
  )
}

/** Match `from package import module as alias; alias.symbol`. */
private predicate memberModuleAttributeReference(
  Expr evidence,
  string targetModule,
  string targetSymbol,
  string kind,
  string bindingForm,
  string resolution
) {
  exists(
    Alias imported, ImportMember member, Name aliasName, Name use,
    Attribute attribute, string packageName
  |
    imported.getValue() = member and
    aliasName = imported.getAsname() and
    use.getVariable() = aliasName.getVariable() and
    attribute.getObject() = use and
    evidence = attribute and
    packageName = member.getModule().(ImportExpr).getImportedModuleName() and
    targetModule = packageName + "." + member.getName() and
    targetSymbol = attribute.getName() and
    kind = referenceKind(attribute) and
    bindingForm = "member_module_alias" and
    resolution = "resolved"
  )
}

/** Match `from module import symbol as alias` at the import site. */
private predicate directImportReference(
  Expr evidence,
  string targetModule,
  string targetSymbol,
  string kind,
  string bindingForm,
  string resolution
) {
  exists(Alias imported, ImportMember member |
    imported.getValue() = member and
    evidence = member and
    targetModule = member.getModule().(ImportExpr).getImportedModuleName() and
    targetSymbol = member.getName() and
    kind = "imports" and
    bindingForm = "symbol_import" and
    resolution = "resolved"
  )
}

/** Match a use of `from module import symbol as alias`. */
private predicate directSymbolReference(
  Expr evidence,
  string targetModule,
  string targetSymbol,
  string kind,
  string bindingForm,
  string resolution
) {
  exists(Alias imported, ImportMember member, Name aliasName, Name use |
    imported.getValue() = member and
    aliasName = imported.getAsname() and
    use.getVariable() = aliasName.getVariable() and
    use != aliasName and
    evidence = use and
    targetModule = member.getModule().(ImportExpr).getImportedModuleName() and
    targetSymbol = member.getName() and
    kind = referenceKind(use) and
    bindingForm = "symbol_alias" and
    resolution = "resolved"
  )
}

/** Match a target-module star import, whose selected symbol is unknown. */
private predicate starImportReference(
  Expr evidence,
  string targetModule,
  string targetSymbol,
  string kind,
  string bindingForm,
  string resolution
) {
  exists(ImportStar star |
    evidence = star.getModuleExpr() and
    targetModule = star.getModuleExpr().getImportedModuleName() and
    targetSymbol = "*" and
    kind = "reads" and
    bindingForm = "star_import" and
    resolution = "unresolved"
  )
}

/** Match `getattr(module_alias, value)`, whose selected symbol is dynamic. */
private predicate dynamicAttributeReference(
  Expr evidence,
  string targetModule,
  string targetSymbol,
  string kind,
  string bindingForm,
  string resolution
) {
  exists(
    Alias imported, ImportExpr importExpr, Name aliasName, Name use,
    Call call, Name getattrName
  |
    imported.getValue() = importExpr and
    aliasName = imported.getAsname() and
    use.getVariable() = aliasName.getVariable() and
    call.getFunc() = getattrName and
    getattrName.getId() = "getattr" and
    call.getPositionalArg(0) = use and
    evidence = call and
    targetModule = importExpr.getImportedModuleName() and
    targetSymbol = "*" and
    kind = "reads" and
    bindingForm = "dynamic_attribute" and
    resolution = "unresolved"
  )
}

/** Match dynamic lookup through `from package import module as alias`. */
private predicate dynamicMemberAttributeReference(
  Expr evidence,
  string targetModule,
  string targetSymbol,
  string kind,
  string bindingForm,
  string resolution
) {
  exists(
    Alias imported, ImportMember member, Name aliasName, Name use,
    Call call, Name getattrName, string packageName
  |
    imported.getValue() = member and
    aliasName = imported.getAsname() and
    use.getVariable() = aliasName.getVariable() and
    call.getFunc() = getattrName and
    getattrName.getId() = "getattr" and
    call.getPositionalArg(0) = use and
    evidence = call and
    packageName = member.getModule().(ImportExpr).getImportedModuleName() and
    targetModule = packageName + "." + member.getName() and
    targetSymbol = "*" and
    kind = "reads" and
    bindingForm = "dynamic_member_attribute" and
    resolution = "unresolved"
  )
}

/** Match a write that changes the meaning of an imported module alias. */
private predicate moduleAliasRebindingReference(
  Expr evidence,
  string targetModule,
  string targetSymbol,
  string kind,
  string bindingForm,
  string resolution
) {
  exists(Alias imported, ImportExpr importExpr, Name aliasName, Name definition |
    imported.getValue() = importExpr and
    aliasName = imported.getAsname() and
    definition.getVariable() = aliasName.getVariable() and
    definition != aliasName and
    definition.isDefinition() and
    evidence = definition and
    targetModule = importExpr.getImportedModuleName() and
    targetSymbol = "*" and
    kind = "writes" and
    bindingForm = "alias_rebinding" and
    resolution = "unresolved"
  )
}

/** Match a write that changes the meaning of a directly imported symbol. */
private predicate symbolAliasRebindingReference(
  Expr evidence,
  string targetModule,
  string targetSymbol,
  string kind,
  string bindingForm,
  string resolution
) {
  exists(Alias imported, ImportMember member, Name aliasName, Name definition |
    imported.getValue() = member and
    aliasName = imported.getAsname() and
    definition.getVariable() = aliasName.getVariable() and
    definition != aliasName and
    definition.isDefinition() and
    evidence = definition and
    targetModule = member.getModule().(ImportExpr).getImportedModuleName() and
    targetSymbol = member.getName() and
    kind = "writes" and
    bindingForm = "alias_rebinding" and
    resolution = "unresolved"
  )
}

private predicate transitionReference(
  Expr evidence,
  string targetModule,
  string targetSymbol,
  string kind,
  string bindingForm,
  string resolution
) {
  moduleAttributeReference(
    evidence, targetModule, targetSymbol, kind, bindingForm, resolution
  )
  or
  memberModuleAttributeReference(
    evidence, targetModule, targetSymbol, kind, bindingForm, resolution
  )
  or
  directImportReference(
    evidence, targetModule, targetSymbol, kind, bindingForm, resolution
  )
  or
  directSymbolReference(
    evidence, targetModule, targetSymbol, kind, bindingForm, resolution
  )
  or
  starImportReference(
    evidence, targetModule, targetSymbol, kind, bindingForm, resolution
  )
  or
  dynamicAttributeReference(
    evidence, targetModule, targetSymbol, kind, bindingForm, resolution
  )
  or
  dynamicMemberAttributeReference(
    evidence, targetModule, targetSymbol, kind, bindingForm, resolution
  )
  or
  moduleAliasRebindingReference(
    evidence, targetModule, targetSymbol, kind, bindingForm, resolution
  )
  or
  symbolAliasRebindingReference(
    evidence, targetModule, targetSymbol, kind, bindingForm, resolution
  )
}

from AstNode source, AstNode sourceBinding, Expr evidence,
  string targetModule, string targetSymbol, string kind,
  string bindingForm, string resolution
where
  transitionReference(
    evidence, targetModule, targetSymbol, kind, bindingForm, resolution
  ) and
  referenceOwner(evidence, source, sourceBinding)
select source.getLocation().getFile().getRelativePath(),
  sourceBinding.getLocation().getStartLine(), sourceBinding.getLocation().getStartColumn(),
  targetModule, targetSymbol, kind,
  evidence.getLocation().getFile().getRelativePath(),
  evidence.getLocation().getStartLine(), evidence.getLocation().getStartColumn(),
  bindingForm, resolution
