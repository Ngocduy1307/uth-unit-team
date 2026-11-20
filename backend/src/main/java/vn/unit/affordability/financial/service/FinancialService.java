package vn.unit.affordability.financial.service;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import vn.unit.affordability.dossier.repository.DossierRepository;
import vn.unit.affordability.financial.dto.AffordabilitySnapshotResponse;
import vn.unit.affordability.financial.dto.CreateObligationRequest;
import vn.unit.affordability.financial.dto.EvaluateAffordabilityRequest;
import vn.unit.affordability.financial.dto.ObligationResponse;
import vn.unit.affordability.financial.model.AffordabilitySnapshot;
import vn.unit.affordability.financial.model.Obligation;
import vn.unit.affordability.financial.repository.AffordabilitySnapshotRepository;
import vn.unit.affordability.financial.repository.ObligationRepository;
import vn.unit.affordability.shared.exception.ResourceNotFoundException;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.util.List;
import java.util.UUID;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class FinancialService {

    private final ObligationRepository obligationRepository;
    private final AffordabilitySnapshotRepository snapshotRepository;
    private final DossierRepository dossierRepository;

    @Transactional
    public ObligationResponse createObligation(CreateObligationRequest request) {
        requireDossierExists(request.getDossierId());
        Obligation obligation = Obligation.builder()
                .id(UUID.randomUUID().toString())
                .dossierId(request.getDossierId())
                .institutionName(request.getInstitutionName())
                .obligationType(request.getObligationType())
                .monthlyPayment(request.getMonthlyPayment())
                .totalBalance(request.getTotalBalance())
                .remainingTenorMonths(request.getRemainingTenorMonths())
                .interestRate(request.getInterestRate())
                .source(request.getSource())
                .isDuplicated(request.getIsDuplicated() != null ? request.getIsDuplicated() : false)
                .isIncludedInDti(request.getIsIncludedInDti() != null ? request.getIsIncludedInDti() : true)
                .notes(request.getNotes())
                .build();
        return toObligationResponse(obligationRepository.save(obligation));
    }

    public List<ObligationResponse> getObligationsByDossierId(String dossierId) {
        requireDossierExists(dossierId);
        return obligationRepository.findByDossierId(dossierId).stream()
                .map(this::toObligationResponse)
                .toList();
    }

    @Transactional
    public AffordabilitySnapshotResponse evaluate(EvaluateAffordabilityRequest request) {
        requireDossierExists(request.getDossierId());

        BigDecimal i = request.getEligibleNetIncome();
        BigDecimal declared = request.getDeclaredLivingExpenses();
        BigDecimal floor = request.getFloorLivingExpenses();
        BigDecimal e = declared.max(floor);

        BigDecimal d = obligationRepository.findByDossierIdAndIsIncludedInDtiTrue(request.getDossierId())
                .stream()
                .map(Obligation::getMonthlyPayment)
                .reduce(BigDecimal.ZERO, BigDecimal::add);

        BigDecimal p = calculateMonthlyPayment(
                request.getProposedLoanAmount(),
                request.getProposedInterestRate(),
                request.getProposedLoanTenorMonths());

        BigDecimal baselineResidual = i.subtract(e).subtract(d).subtract(p);
        BigDecimal baselineDti = i.compareTo(BigDecimal.ZERO) == 0
                ? BigDecimal.ZERO
                : d.add(p).divide(i, 4, RoundingMode.HALF_UP);

        BigDecimal i1 = i.multiply(new BigDecimal("0.80"));
        BigDecimal stress1Residual = i1.subtract(e).subtract(d).subtract(p);
        BigDecimal stress1Dti = i1.compareTo(BigDecimal.ZERO) == 0
                ? BigDecimal.ZERO
                : d.add(p).divide(i1, 4, RoundingMode.HALF_UP);

        BigDecimal e2 = e.multiply(new BigDecimal("1.10"));
        BigDecimal stress2Residual = i1.subtract(e2).subtract(d).subtract(p);
        BigDecimal stress2Dti = stress1Dti;

        BigDecimal maxDtiLimit = new BigDecimal("0.5000");
        BigDecimal minResidualLimit = new BigDecimal("5000000.00");

        String policyStatus = determinePolicyStatus(
                baselineResidual, baselineDti,
                stress1Residual, stress1Dti,
                stress2Residual, stress2Dti,
                maxDtiLimit, minResidualLimit);

        int nextVersion = snapshotRepository.findByDossierIdOrderBySnapshotVersionDesc(request.getDossierId())
                .stream()
                .findFirst()
                .map(s -> s.getSnapshotVersion() + 1)
                .orElse(1);

        AffordabilitySnapshot snapshot = AffordabilitySnapshot.builder()
                .id(UUID.randomUUID().toString())
                .dossierId(request.getDossierId())
                .snapshotVersion(nextVersion)
                .formulaVersion("V1")
                .eligibleNetIncome(i)
                .declaredLivingExpenses(declared)
                .floorLivingExpenses(floor)
                .effectiveLivingExpenses(e)
                .existingDebtService(d)
                .proposedLoanAmount(request.getProposedLoanAmount())
                .proposedLoanTenorMonths(request.getProposedLoanTenorMonths())
                .proposedInterestRate(request.getProposedInterestRate())
                .proposedLoanPayment(p)
                .baselineResidual(baselineResidual)
                .baselineDti(baselineDti)
                .stress1Residual(stress1Residual)
                .stress1Dti(stress1Dti)
                .stress2Residual(stress2Residual)
                .stress2Dti(stress2Dti)
                .maxDtiLimit(maxDtiLimit)
                .minResidualLimit(minResidualLimit)
                .policyStatus(policyStatus)
                .calculatedBy(request.getCalculatedBy())
                .build();

        return toSnapshotResponse(snapshotRepository.save(snapshot));
    }

    public List<AffordabilitySnapshotResponse> getSnapshotsByDossierId(String dossierId) {
        requireDossierExists(dossierId);
        return snapshotRepository.findByDossierIdOrderBySnapshotVersionDesc(dossierId).stream()
                .map(this::toSnapshotResponse)
                .toList();
    }

    public AffordabilitySnapshotResponse getLatestSnapshot(String dossierId) {
        requireDossierExists(dossierId);
        return snapshotRepository.findByDossierIdOrderBySnapshotVersionDesc(dossierId).stream()
                .findFirst()
                .map(this::toSnapshotResponse)
                .orElseThrow(() -> new ResourceNotFoundException("No snapshot found for dossier: " + dossierId));
    }

    private BigDecimal calculateMonthlyPayment(BigDecimal principal, BigDecimal annualRatePercent, int tenorMonths) {
        BigDecimal monthlyRate = annualRatePercent
                .divide(BigDecimal.valueOf(100), 10, RoundingMode.HALF_UP)
                .divide(BigDecimal.valueOf(12), 10, RoundingMode.HALF_UP);

        if (monthlyRate.compareTo(BigDecimal.ZERO) == 0) {
            return principal.divide(BigDecimal.valueOf(tenorMonths), 2, RoundingMode.HALF_UP);
        }

        BigDecimal onePlusR = BigDecimal.ONE.add(monthlyRate);
        BigDecimal onePlusRPowN = onePlusR.pow(tenorMonths, new MathContext(15, RoundingMode.HALF_UP));
        BigDecimal numerator = principal.multiply(monthlyRate).multiply(onePlusRPowN);
        BigDecimal denominator = onePlusRPowN.subtract(BigDecimal.ONE);
        return numerator.divide(denominator, 2, RoundingMode.HALF_UP);
    }

    private String determinePolicyStatus(
            BigDecimal baseResidual, BigDecimal baseDti,
            BigDecimal s1Residual, BigDecimal s1Dti,
            BigDecimal s2Residual, BigDecimal s2Dti,
            BigDecimal maxDti, BigDecimal minResidual) {

        boolean baseOk = baseDti.compareTo(maxDti) <= 0 && baseResidual.compareTo(minResidual) >= 0;
        boolean stress1Ok = s1Dti.compareTo(maxDti) <= 0 && s1Residual.compareTo(minResidual) >= 0;
        boolean stress2Ok = s2Dti.compareTo(maxDti) <= 0 && s2Residual.compareTo(minResidual) >= 0;

        if (baseOk && stress1Ok && stress2Ok) return "PASS";
        if (baseOk) return "CONDITIONAL";
        return "FAIL";
    }

    private void requireDossierExists(String dossierId) {
        if (!dossierRepository.existsById(dossierId)) {
            throw new ResourceNotFoundException("Dossier not found: " + dossierId);
        }
    }

    private ObligationResponse toObligationResponse(Obligation o) {
        return ObligationResponse.builder()
                .id(o.getId())
                .dossierId(o.getDossierId())
                .institutionName(o.getInstitutionName())
                .obligationType(o.getObligationType())
                .monthlyPayment(o.getMonthlyPayment())
                .totalBalance(o.getTotalBalance())
                .remainingTenorMonths(o.getRemainingTenorMonths())
                .interestRate(o.getInterestRate())
                .source(o.getSource())
                .isDuplicated(o.getIsDuplicated())
                .isIncludedInDti(o.getIsIncludedInDti())
                .notes(o.getNotes())
                .createdAt(o.getCreatedAt())
                .build();
    }

    private AffordabilitySnapshotResponse toSnapshotResponse(AffordabilitySnapshot s) {
        return AffordabilitySnapshotResponse.builder()
                .id(s.getId())
                .dossierId(s.getDossierId())
                .snapshotVersion(s.getSnapshotVersion())
                .formulaVersion(s.getFormulaVersion())
                .eligibleNetIncome(s.getEligibleNetIncome())
                .declaredLivingExpenses(s.getDeclaredLivingExpenses())
                .floorLivingExpenses(s.getFloorLivingExpenses())
                .effectiveLivingExpenses(s.getEffectiveLivingExpenses())
                .existingDebtService(s.getExistingDebtService())
                .proposedLoanAmount(s.getProposedLoanAmount())
                .proposedLoanTenorMonths(s.getProposedLoanTenorMonths())
                .proposedInterestRate(s.getProposedInterestRate())
                .proposedLoanPayment(s.getProposedLoanPayment())
                .baselineResidual(s.getBaselineResidual())
                .baselineDti(s.getBaselineDti())
                .stress1Residual(s.getStress1Residual())
                .stress1Dti(s.getStress1Dti())
                .stress2Residual(s.getStress2Residual())
                .stress2Dti(s.getStress2Dti())
                .maxDtiLimit(s.getMaxDtiLimit())
                .minResidualLimit(s.getMinResidualLimit())
                .policyStatus(s.getPolicyStatus())
                .policyNotes(s.getPolicyNotes())
                .calculatedBy(s.getCalculatedBy())
                .createdAt(s.getCreatedAt())
                .build();
    }
}
