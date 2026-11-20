package vn.unit.affordability.financial.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
@JsonInclude(JsonInclude.Include.NON_NULL)
public class AffordabilitySnapshotResponse {

    private String id;
    private String dossierId;
    private Integer snapshotVersion;
    private String formulaVersion;
    private BigDecimal eligibleNetIncome;
    private BigDecimal declaredLivingExpenses;
    private BigDecimal floorLivingExpenses;
    private BigDecimal effectiveLivingExpenses;
    private BigDecimal existingDebtService;
    private BigDecimal proposedLoanAmount;
    private Integer proposedLoanTenorMonths;
    private BigDecimal proposedInterestRate;
    private BigDecimal proposedLoanPayment;
    private BigDecimal baselineResidual;
    private BigDecimal baselineDti;
    private BigDecimal stress1Residual;
    private BigDecimal stress1Dti;
    private BigDecimal stress2Residual;
    private BigDecimal stress2Dti;
    private BigDecimal maxDtiLimit;
    private BigDecimal minResidualLimit;
    private String policyStatus;
    private String policyNotes;
    private String calculatedBy;
    private OffsetDateTime createdAt;
}
